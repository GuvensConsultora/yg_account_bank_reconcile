# Yagüven C.G. — Licencia LGPL-3.
"""Datos para la pantalla de conciliación (client action OWL).

Todo lo que modifica pasa por `yg_conciliar` / `action_undo_reconciliation` / reglas:
estos métodos sólo leen y arman diccionarios serializables.
"""
from odoo import api, fields, models
from odoo.tools import float_is_zero


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    # ------------------------------------------------------------------ lectura
    def _yg_pantalla_linea_dict(self):
        self.ensure_one()
        resumen = ""
        if self.is_reconciled:
            _liq, _sus, otras = self._seek_for_lines()
            partes = []
            for o in otras:
                contra = (o.matched_debit_ids.debit_move_id | o.matched_credit_ids.credit_move_id).move_id
                partes.append(", ".join(contra.mapped("name")) if contra else o.account_id.display_name)
            resumen = " · ".join(filter(None, partes))
            reglas = otras.reconcile_model_id
            if reglas:
                resumen = "regla «%s»" % ", ".join(reglas.mapped("name"))
        return {
            "id": self.id,
            "fecha": self.date.isoformat(),
            "concepto": self.payment_ref or "",
            "comprobante": self.ref or "",
            "contacto": self.partner_id.display_name or "",
            "monto": self.amount,
            "conciliado": self.is_reconciled,
            "resumen": resumen,
        }

    def _yg_detalle_conciliacion(self):
        """Cómo y por qué quedó conciliado el movimiento, para mostrarlo en la pantalla."""
        self.ensure_one()
        moneda = self.company_id.currency_id
        total = abs(self.amount)
        _liq, _sus, otras = self._seek_for_lines()
        renglones, documentos, reglas = [], [], self.env["account.reconcile.model"]
        for o in otras:
            contra = (o.matched_debit_ids.debit_move_id | o.matched_credit_ids.credit_move_id)
            reglas |= o.reconcile_model_id
            renglones.append({
                "cuenta": o.account_id.display_name,
                "etiqueta": o.name or "",
                "importe": abs(o.balance),
                "porcentaje": round(abs(o.balance) / total * 100, 1) if total else 0,
                "documento": ", ".join(contra.move_id.mapped("name")),
            })
            for mov in contra.move_id:
                documentos.append({"nombre": mov.name, "contacto": mov.partner_id.display_name or "",
                                   "tipo": dict(mov._fields["move_type"]._description_selection(self.env)).get(mov.move_type, "")})

        explicaciones = []
        for regla in reglas:
            condicion = {"contains": "contiene", "not_contains": "no contiene", "match_regex": "cumple la expresión"}.get(
                regla.match_label, "")
            texto = "Se aplicó la regla «%s»: el concepto del banco %s «%s»" % (regla.name, condicion, regla.match_label_param or "")
            if regla.match_journal_ids:
                texto += " y el movimiento es del banco %s" % ", ".join(regla.match_journal_ids.mapped("name"))
            texto += ". Es una regla %s." % ("automática (se concilia sola con «Aplicar reglas»)" if regla.trigger == "auto_reconcile"
                                            else "manual (propone los renglones y la confirmás vos)")
            partes = []
            lineas_regla = regla.line_ids.sorted("sequence")
            for i, rl in enumerate(lineas_regla):
                ultima = i == len(lineas_regla) - 1 and i > 0
                if ultima:
                    partes.append("el resto a %s" % rl.account_id.display_name)
                elif rl.amount_type in ("percentage", "percentage_st_line"):
                    partes.append("%s%% a %s" % (rl.amount_string, rl.account_id.display_name))
                elif rl.amount_type == "fixed":
                    partes.append("%s fijo a %s" % (rl.amount_string, rl.account_id.display_name))
            if len(partes) == 1 and lineas_regla[:1].amount_string == "100":
                partes = ["todo a %s" % lineas_regla[:1].account_id.display_name]
            if partes:
                texto += " Reparte: " + "; ".join(partes) + "."
            explicaciones.append(texto)
        if documentos:
            explicaciones.append("Se canceló contra %s: el movimiento del banco paga o cobra ese comprobante y su pendiente "
                                 "baja en el mismo importe." % ", ".join("%s (%s%s)" % (d["nombre"], d["tipo"],
                                 (", " + d["contacto"]) if d["contacto"] else "") for d in documentos))
        if not reglas and not documentos:
            explicaciones.append("Conciliación manual: se imputó a cuenta desde la pantalla, sin regla.")

        nota = self.move_id.message_ids.filtered(lambda m: "Conciliación bancaria" in (m.body or ""))[:1]
        cuando = fields.Datetime.context_timestamp(self, nota.date).strftime("%d/%m/%Y %H:%M") if nota else ""
        return {
            "explicaciones": explicaciones,
            "renglones": renglones,
            "por": nota.author_id.display_name if nota else "",
            "cuando": cuando,
            "observacion": self.yg_conciliacion_obs or "",
            "total": total,
        }

    @api.model
    def yg_pantalla_datos(self, journal_id, filtro="pendientes", texto=""):
        journal = self.env["account.journal"].browse(journal_id) if journal_id else \
            self.env["account.journal"].search([("type", "=", "bank"), ("company_id", "in", self.env.companies.ids)],
                                               order="sequence, id", limit=1)
        dominio = [("journal_id", "=", journal.id)]
        if filtro == "pendientes":
            dominio.append(("is_reconciled", "=", False))
        elif filtro == "conciliados":
            dominio.append(("is_reconciled", "=", True))
        if texto:
            dominio += ["|", "|", ("payment_ref", "ilike", texto), ("ref", "ilike", texto),
                        ("partner_id.name", "ilike", texto)]
        lineas = self.search(dominio, order="date, id", limit=500)
        todas = self.search_count([("journal_id", "=", journal.id)])
        pendientes = self.search_count([("journal_id", "=", journal.id), ("is_reconciled", "=", False)])
        return {
            "journal": {"id": journal.id, "name": journal.name, "code": journal.code},
            "currency_id": journal.company_id.currency_id.id,
            "lineas": [l._yg_pantalla_linea_dict() for l in lineas],
            "pendientes": pendientes,
            "conciliados": todas - pendientes,
        }

    def _yg_aml_dict(self, aml, objetivo):
        pendiente = abs(aml.amount_residual)
        return {
            "aml_id": aml.id,
            "fecha": aml.date.isoformat() if aml.date else "",
            "vencimiento": aml.date_maturity.isoformat() if aml.date_maturity else "",
            "comprobante": aml.move_id.name or "",
            "contacto": aml.partner_id.display_name or "",
            "cuenta": aml.account_id.display_name,
            "etiqueta": aml.name or "",
            "pendiente": pendiente,
            "mismo_importe": float_is_zero(pendiente - objetivo, precision_digits=2),
        }

    @api.model
    def yg_pantalla_linea(self, st_line_id):
        linea = self.browse(st_line_id)
        objetivo = abs(linea.amount)
        datos = {"linea": linea._yg_pantalla_linea_dict(), "sugerencias": [], "regla": False, "detalle": False}
        if linea.is_reconciled:
            datos["detalle"] = linea._yg_detalle_conciliacion()
            return datos
        sugeridas = self.yg_partidas_sugeridas(linea, limite=12)
        sugerencias = []
        for a in sugeridas:
            d = self._yg_aml_dict(a, objetivo)
            d["relevante"] = d["mismo_importe"] or bool(linea.partner_id and a.partner_id == linea.partner_id)
            sugerencias.append(d)
        datos["sugerencias"] = sugerencias
        regla = linea.yg_regla_para()
        imputaciones = regla and linea._yg_imputaciones_de_regla(regla)
        if imputaciones:
            cuentas = self.env["account.account"].browse([i["account_id"] for i in imputaciones])
            nombres = {c.id: c.display_name for c in cuentas}
            datos["regla"] = {
                "id": regla.id,
                "nombre": regla.name,
                "renglones": [dict(i, account_name=nombres[i["account_id"]]) for i in imputaciones],
            }
        return datos

    @api.model
    def yg_pantalla_buscar(self, st_line_id, texto):
        linea = self.browse(st_line_id)
        dominio = linea._get_default_amls_matching_domain()
        if texto:
            dominio += ["|", "|", "|", ("move_id.name", "ilike", texto), ("name", "ilike", texto),
                        ("partner_id.name", "ilike", texto), ("ref", "ilike", texto)]
        amls = self.env["account.move.line"].search(dominio, order="date_maturity, id", limit=30)
        return [self._yg_aml_dict(a, abs(linea.amount)) for a in amls]

    @api.model
    def yg_pantalla_cuentas(self):
        cuentas = self.env["account.account"].search([
            ("account_type", "not in", ("asset_receivable", "liability_payable", "off_balance")),
            ("active", "=", True),
        ], order="code")
        return [{"id": c.id, "name": c.display_name} for c in cuentas]

    # ------------------------------------------------------------------ escritura
    @api.model
    def yg_pantalla_conciliar(self, st_line_id, partidas, imputaciones, observacion="", regla_id=False):
        """partidas: [[aml_id, importe]]; imputaciones: [{account_id, importe, name}].
        Devuelve el id del próximo movimiento pendiente del mismo banco (o False)."""
        linea = self.browse(st_line_id)
        amls = self.env["account.move.line"].browse([p[0] for p in partidas])
        linea.yg_conciliar(
            partidas=[(aml, p[1]) for aml, p in zip(amls, partidas)],
            imputaciones=[{"account_id": int(i["account_id"]), "importe": float(i["importe"]),
                           "name": i.get("name") or "", "partner_id": False} for i in imputaciones],
            observacion=observacion,
            regla=self.env["account.reconcile.model"].browse(regla_id) if regla_id else None,
        )
        proxima = self.search([("journal_id", "=", linea.journal_id.id), ("is_reconciled", "=", False),
                               "|", ("date", ">", linea.date), "&", ("date", "=", linea.date), ("id", ">", linea.id)],
                              order="date, id", limit=1) or self.search(
            [("journal_id", "=", linea.journal_id.id), ("is_reconciled", "=", False)], order="date, id", limit=1)
        return proxima.id or False

    @api.model
    def yg_pantalla_deshacer(self, st_line_id):
        self.browse(st_line_id).action_undo_reconciliation()
        return True

    @api.model
    def yg_pantalla_aplicar_reglas(self, journal_id):
        lineas = self.search([("journal_id", "=", journal_id), ("is_reconciled", "=", False)])
        antes = len(lineas)
        lineas.yg_aplicar_reglas()
        despues = self.search_count([("journal_id", "=", journal_id), ("is_reconciled", "=", False)])
        return {"aplicadas": antes - despues, "pendientes": despues}

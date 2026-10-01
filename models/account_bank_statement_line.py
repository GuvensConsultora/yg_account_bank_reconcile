# Yagüven C.G. — Licencia LGPL-3.
from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    def yg_conciliar(self, partidas=None, imputaciones=None):
        """Concilia la línea del extracto: reemplaza la línea de la cuenta transitoria
        por las contrapartidas reales y concilia las partidas pendientes elegidas.

        :param partidas: [(account.move.line, importe)] partidas pendientes (factura,
            pago, cheque diferido…) y cuánto aplicar de cada una, en positivo.
        :param imputaciones: [{"account_id": int, "importe": float, "name": str,
            "partner_id": int|False}] renglones a cuenta (impuesto al cheque, comisión…),
            importe en positivo; el signo lo pone el movimiento del banco.

        La suma de partidas e imputaciones tiene que ser igual al movimiento del banco
        al centavo; si no, no concilia nada. Es el mismo patrón que usa el nativo en
        `action_undo_reconciliation`, al revés. Sólo moneda de la compañía.
        """
        self.ensure_one()
        partidas = partidas or []
        imputaciones = imputaciones or []
        moneda = self.company_id.currency_id
        if self.foreign_currency_id or (self.journal_id.currency_id and self.journal_id.currency_id != moneda):
            raise UserError("Por ahora la conciliación sólo admite movimientos en %s." % moneda.name)
        if self.is_reconciled:
            raise UserError("La línea «%s» ya está conciliada. Para cambiarla, primero deshacé la conciliación."
                            % self.payment_ref)
        if not partidas and not imputaciones:
            raise UserError("Elegí al menos una partida pendiente o un renglón a cuenta.")

        liquidez, transitoria, otras = self._seek_for_lines()
        if otras:
            raise UserError("La línea «%s» ya tiene contrapartidas cargadas: deshacé la conciliación antes."
                            % self.payment_ref)
        # Movimiento del banco visto desde la contrapartida: si el banco debita (-), las
        # contrapartidas van al debe (+) y viceversa.
        signo = -1 if liquidez.balance < 0 else 1
        objetivo = abs(liquidez.balance)

        nuevas = []
        for aml, importe in partidas:
            importe = moneda.round(importe)
            if float_compare(importe, abs(aml.amount_residual), precision_rounding=moneda.rounding) > 0:
                raise UserError("No se puede aplicar %s a «%s»: su pendiente es %s."
                                % (importe, aml.display_name, abs(aml.amount_residual)))
            # La contrapartida cancela la partida: signo opuesto a su pendiente.
            balance = -importe if aml.amount_residual > 0 else importe
            nuevas.append(("partida", aml, {
                "name": aml.name or aml.move_id.name or self.payment_ref,
                "account_id": aml.account_id.id,
                "partner_id": aml.partner_id.id,
                "balance": balance,
                "amount_currency": balance,
                "currency_id": moneda.id,
            }))
        for imp in imputaciones:
            importe = moneda.round(imp["importe"])
            balance = -signo * importe
            nuevas.append(("cuenta", None, {
                "name": imp.get("name") or self.payment_ref,
                "account_id": imp["account_id"],
                "partner_id": imp.get("partner_id") or self.partner_id.id,
                "balance": balance,
                "amount_currency": balance,
                "currency_id": moneda.id,
            }))

        total = sum(v["balance"] for _t, _a, v in nuevas)
        if not float_is_zero(total + liquidez.balance, precision_rounding=moneda.rounding):
            raise UserError("Lo asignado (%s) no coincide con el movimiento del banco (%s). Falta asignar %s."
                            % (moneda.round(abs(total)), objetivo, moneda.round(objetivo - abs(total))))

        comandos = [Command.delete(l.id) for l in transitoria]
        comandos += [Command.create(dict(v, move_id=self.move_id.id)) for _t, _a, v in nuevas]
        # Si la línea no tenía contacto y todas las partidas son del mismo, se lo asigna.
        socios = {aml.partner_id for t, aml, _v in nuevas if t == "partida" and aml.partner_id}
        if not self.partner_id and len(socios) == 1:
            comandos.append(Command.update(liquidez.id, {"partner_id": socios.pop().id}))

        lineas_antes = self.move_id.line_ids
        self.with_context(force_delete=True, skip_readonly_check=True).write({"line_ids": comandos})
        creadas = self.move_id.line_ids - lineas_antes

        # Conciliar cada contrapartida con su partida (mismo orden de creación).
        contra = iter(creadas.sorted("id"))
        for tipo, aml, _vals in nuevas:
            linea = next(contra)
            if tipo == "partida":
                (linea + aml).reconcile()
        return True

    @api.model
    def yg_partidas_sugeridas(self, linea, limite=20):
        """Partidas pendientes candidatas para una línea: mismo importe, mismo contacto o
        cuentas conciliables de pagos/cheques en tránsito. Usa el dominio nativo."""
        dominio = linea._get_default_amls_matching_domain()
        amls = self.env["account.move.line"].search(dominio, limit=500)
        objetivo = abs(linea.amount)

        def puntaje(aml):
            p = 0
            if float_is_zero(abs(aml.amount_residual) - objetivo, precision_digits=2):
                p += 4
            if linea.partner_id and aml.partner_id == linea.partner_id:
                p += 2
            if (aml.amount_residual > 0) == (linea.amount > 0):
                p += 1  # el banco cobra y la partida es a cobrar, o paga y es a pagar
            return p

        return amls.sorted(lambda a: (-puntaje(a), a.date_maturity or a.date))[:limite]

    def action_yg_conciliar(self):
        """Abre la pantalla de conciliación de esta línea."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Conciliar — %s %s" % (self.date.strftime("%d/%m/%Y"), self.payment_ref or ""),
            "res_model": "yg.conciliar",
            "view_mode": "form",
            "target": "new",
            "context": {"default_st_line_id": self.id},
        }

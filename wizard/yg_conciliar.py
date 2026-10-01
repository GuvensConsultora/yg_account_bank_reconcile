# Yagüven C.G. — Licencia LGPL-3.
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class YgConciliar(models.TransientModel):
    _name = "yg.conciliar"
    _description = "Conciliar movimiento del banco"

    st_line_id = fields.Many2one("account.bank.statement.line", string="Movimiento", required=True, readonly=True)
    journal_id = fields.Many2one(related="st_line_id.journal_id", string="Banco")
    fecha = fields.Date(related="st_line_id.date", string="Fecha")
    concepto = fields.Char(related="st_line_id.payment_ref", string="Concepto")
    comprobante = fields.Char(related="st_line_id.ref", string="Comprobante")
    monto = fields.Monetary(related="st_line_id.amount", string="Importe del banco")
    currency_id = fields.Many2one(related="st_line_id.company_id.currency_id", string="Moneda")

    partida_ids = fields.One2many("yg.conciliar.partida", "wizard_id", string="Partidas pendientes")
    cuenta_ids = fields.One2many("yg.conciliar.cuenta", "wizard_id", string="A cuenta")
    agregar_aml_id = fields.Many2one(
        "account.move.line", string="Agregar otra partida",
        domain="[('reconciled', '=', False), ('parent_state', '=', 'posted'), ('account_id.reconcile', '=', True), "
               "('company_id', '=', company_id), ('statement_line_id', '!=', st_line_id)]",
        help="Buscá una partida pendiente que no esté entre las sugeridas.")
    company_id = fields.Many2one(related="st_line_id.company_id")

    regla_id = fields.Many2one("account.reconcile.model", string="Regla aplicada", readonly=True,
                               help="Modelo de conciliación que precargó los renglones a cuenta.")
    asignado = fields.Monetary(compute="_compute_asignado", string="Asignado")
    falta = fields.Monetary(compute="_compute_asignado", string="Falta asignar")

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        linea = self.env["account.bank.statement.line"].browse(vals.get("st_line_id") or self.env.context.get("active_id"))
        if linea:
            vals["st_line_id"] = linea.id
            sugeridas = self.env["account.bank.statement.line"].yg_partidas_sugeridas(linea)
            vals["partida_ids"] = [fields.Command.create(self._valores_partida(aml)) for aml in sugeridas]
            regla = linea.yg_regla_para()
            imputaciones = regla and linea._yg_imputaciones_de_regla(regla)
            if imputaciones:
                vals["regla_id"] = regla.id
                vals["cuenta_ids"] = [fields.Command.create({
                    "account_id": i["account_id"], "importe": i["importe"], "name": i["name"],
                    "partner_id": i["partner_id"]}) for i in imputaciones]
        return vals

    @api.model
    def _valores_partida(self, aml):
        return {"aml_id": aml.id, "pendiente": abs(aml.amount_residual), "seleccionar": False, "importe": 0.0}

    @api.depends("monto", "partida_ids.seleccionar", "partida_ids.importe", "cuenta_ids.importe")
    def _compute_asignado(self):
        for w in self:
            asignado = sum(p.importe for p in w.partida_ids if p.seleccionar) + sum(w.cuenta_ids.mapped("importe"))
            w.asignado = asignado
            w.falta = abs(w.monto) - asignado

    @api.onchange("agregar_aml_id")
    def _onchange_agregar_aml_id(self):
        if self.agregar_aml_id:
            if self.agregar_aml_id not in self.partida_ids.aml_id:
                vals = self._valores_partida(self.agregar_aml_id)
                vals.update(seleccionar=True, importe=min(vals["pendiente"], max(self.falta, 0.0)))
                self.partida_ids = [fields.Command.create(vals)]
            self.agregar_aml_id = False

    def _siguiente_pendiente(self):
        return self.env["account.bank.statement.line"].search([
            ("journal_id", "=", self.journal_id.id), ("is_reconciled", "=", False), ("id", "!=", self.st_line_id.id),
        ], order="date, id", limit=1)

    def action_conciliar(self, siguiente=False):
        self.ensure_one()
        if not float_is_zero(self.falta, precision_rounding=self.currency_id.rounding):
            raise UserError("Falta asignar %s para que coincida con el movimiento del banco." % self.falta)
        self.st_line_id.yg_conciliar(
            partidas=[(p.aml_id, p.importe) for p in self.partida_ids if p.seleccionar and p.importe],
            imputaciones=[{"account_id": c.account_id.id, "importe": c.importe, "name": c.name,
                           "partner_id": c.partner_id.id} for c in self.cuenta_ids if c.importe],
        )
        if siguiente:
            proxima = self._siguiente_pendiente()
            if proxima:
                return proxima.action_yg_conciliar()
        return {"type": "ir.actions.act_window_close"}

    def action_conciliar_y_siguiente(self):
        return self.action_conciliar(siguiente=True)


class YgConciliarPartida(models.TransientModel):
    _name = "yg.conciliar.partida"
    _description = "Partida pendiente propuesta para conciliar"
    _order = "seleccionar desc, id"

    wizard_id = fields.Many2one("yg.conciliar", required=True, ondelete="cascade")
    aml_id = fields.Many2one("account.move.line", string="Partida", required=True, readonly=True)
    fecha = fields.Date(related="aml_id.date", string="Fecha")
    vencimiento = fields.Date(related="aml_id.date_maturity", string="Vencimiento")
    comprobante = fields.Many2one(related="aml_id.move_id", string="Comprobante")
    contacto = fields.Many2one(related="aml_id.partner_id", string="Contacto")
    cuenta = fields.Many2one(related="aml_id.account_id", string="Cuenta")
    etiqueta = fields.Text(related="aml_id.name", string="Etiqueta")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    pendiente = fields.Monetary(string="Pendiente", readonly=True)
    seleccionar = fields.Boolean(string="Usar")
    importe = fields.Monetary(string="A aplicar")

    @api.onchange("seleccionar")
    def _onchange_seleccionar(self):
        if self.seleccionar and not self.importe:
            falta = self.wizard_id.falta + self.importe
            self.importe = min(self.pendiente, max(falta, 0.0)) or self.pendiente
        elif not self.seleccionar:
            self.importe = 0.0


class YgConciliarCuenta(models.TransientModel):
    _name = "yg.conciliar.cuenta"
    _description = "Renglón a cuenta en la conciliación"

    wizard_id = fields.Many2one("yg.conciliar", required=True, ondelete="cascade")
    account_id = fields.Many2one("account.account", string="Cuenta", required=True)
    name = fields.Char(string="Etiqueta")
    partner_id = fields.Many2one("res.partner", string="Contacto")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    importe = fields.Monetary(string="Importe")

    @api.onchange("account_id")
    def _onchange_account_id(self):
        if self.account_id and not self.importe:
            self.importe = max(self.wizard_id.falta, 0.0)
        if not self.name:
            self.name = self.wizard_id.concepto

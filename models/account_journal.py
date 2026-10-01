# Yagüven C.G. — Licencia LGPL-3.
from odoo import models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def action_yg_bank_reconcile(self):
        """Lista de movimientos pendientes de conciliar de este banco."""
        self.ensure_one()
        accion = self.env["ir.actions.act_window"]._for_xml_id("yg_account_bank_reconcile.action_yg_bank_reconcile")
        accion["name"] = "Conciliación bancaria — %s" % self.name
        accion["domain"] = [("journal_id", "=", self.id)]
        accion["context"] = {"search_default_pendientes": 1}
        return accion

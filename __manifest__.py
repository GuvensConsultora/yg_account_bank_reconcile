# Yagüven C.G. — Licencia LGPL-3.
{
    'name': 'Conciliación bancaria',
    'version': '20.0.1.0.0',
    'summary': 'Concilia los movimientos del extracto con facturas, pagos, cheques o cuentas (Odoo 20 Community)',
    'description': """
Conciliación bancaria
=====================
Odoo 20 Community trae las piezas de base pero no la pantalla de conciliación.

* Lista «Conciliación bancaria» de movimientos pendientes, con Conciliar y Deshacer.
* Pantalla de conciliación: partidas pendientes sugeridas (mismo importe, mismo contacto,
  cheques diferidos y pagos en tránsito), renglones a cuenta y control de «Falta asignar».
* Concilia al centavo y usa el mismo mecanismo que el «Deshacer» nativo.
* Botón «Conciliar» en la tarjeta de cada banco del tablero.
    """,
    'author': 'Yagüven C.G.',
    'website': 'https://yaguven.com',
    'category': 'Accounting/Accounting',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'security/ir.access.csv',
        'views/yg_conciliar_views.xml',
        'views/account_bank_statement_line_views.xml',
    ],
    'installable': True,
    'application': False,
}

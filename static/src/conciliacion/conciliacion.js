// Yagüven C.G. — Licencia LGPL-3.
//
// Pantalla de conciliación bancaria (client action "yg_conciliacion_bancaria").
// Dos paneles: movimientos del banco a la izquierda y trabajo sobre el movimiento
// elegido a la derecha. Toda modificación pasa por los métodos yg_pantalla_* del
// servidor (que usan el motor yg_conciliar ya probado).
// Odoo 20 / OWL 3: estado con proxy(); en la plantilla, todo lo del componente
// va con `this.` (sin prefijo da undefined en silencio).

import { Component, onWillStart, proxy, useListener, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { formatMonetary } from "@web/views/fields/formatters";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

const MODELO = "account.bank.statement.line";

export class YgConciliacionBancaria extends Component {
    static template = "yaguven_bank_reconcile.Conciliacion";
    static components = { ControlPanel };

    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.actionService = useService("action");
        const ctx = this.props.action.context || {};
        const params = this.props.action.params || {};
        this.state = proxy({
            journalId: params.journal_id || ctx.journal_id || ctx.active_id,
            journal: {},
            currencyId: false,
            filtro: "pendientes",
            texto: "",
            lineas: [],
            pendientes: 0,
            conciliados: 0,
            actualId: false,
            actual: false,
            sugerencias: [],
            elegidas: {}, // aml_id -> {datos, importe}
            renglones: [], // {account_id, account_name, importe, name}
            regla: false,
            reglaId: false,
            detalle: false,
            buscar: "",
            resultados: [],
            observacion: "",
            cuentas: [],
            ocupado: false,
            verTodas: false,
        });
        onWillStart(async () => {
            this.state.cuentas = await this.orm.call(MODELO, "yg_pantalla_cuentas", []);
            await this.cargar();
        });
        useListener(window, "keydown", (ev) => this.onTecla(ev));
    }

    // ------------------------------------------------------------------ datos
    async cargar(seleccionar = undefined) {
        const datos = await this.orm.call(MODELO, "yg_pantalla_datos", [
            this.state.journalId, this.state.filtro, this.state.texto,
        ]);
        this.state.journal = datos.journal;
        this.state.journalId = datos.journal.id;
        this.state.currencyId = datos.currency_id;
        this.state.lineas = datos.lineas;
        this.state.pendientes = datos.pendientes;
        this.state.conciliados = datos.conciliados;
        let id = seleccionar !== undefined ? seleccionar : this.state.actualId;
        if (!id || !datos.lineas.some((l) => l.id === id)) {
            id = datos.lineas.length ? datos.lineas[0].id : false;
        }
        await this.elegir(id);
    }

    async elegir(id) {
        this.state.actualId = id;
        this.state.elegidas = {};
        this.state.renglones = [];
        this.state.resultados = [];
        this.state.buscar = "";
        this.state.observacion = "";
        this.state.regla = false;
        this.state.reglaId = false;
        this.state.detalle = false;
        this.state.verTodas = false;
        if (!id) {
            this.state.actual = false;
            this.state.sugerencias = [];
            return;
        }
        const datos = await this.orm.call(MODELO, "yg_pantalla_linea", [id]);
        this.state.actual = datos.linea;
        this.state.sugerencias = datos.sugerencias;
        this.state.detalle = datos.detalle;
        if (datos.regla) {
            this.state.regla = datos.regla.nombre;
            this.state.reglaId = datos.regla.id;
            this.state.renglones = datos.regla.renglones.map((r) => ({ ...r }));
        }
    }

    // ------------------------------------------------------------------ cálculos
    get objetivo() {
        return this.state.actual ? Math.abs(this.state.actual.monto) : 0;
    }
    get asignado() {
        const p = Object.values(this.state.elegidas).reduce((s, e) => s + (parseFloat(e.importe) || 0), 0);
        const c = this.state.renglones.reduce((s, r) => s + (parseFloat(r.importe) || 0), 0);
        return Math.round((p + c) * 100) / 100;
    }
    get falta() {
        return Math.round((this.objetivo - this.asignado) * 100) / 100;
    }
    get cuadra() {
        return this.state.actual && Math.abs(this.falta) < 0.005;
    }
    get porcentaje() {
        if (!this.objetivo) {
            return 0;
        }
        return Math.min(100, Math.max(0, (this.asignado / this.objetivo) * 100));
    }
    money(valor) {
        return formatMonetary(valor, { currencyId: this.state.currencyId });
    }
    fecha(iso) {
        if (!iso) {
            return "";
        }
        const [a, m, d] = iso.split("-");
        return `${d}/${m}/${a}`;
    }
    get sugerenciasVisibles() {
        const todas = this.state.sugerencias;
        return this.state.verTodas ? todas : todas.filter((s) => s.relevante || this.esElegida(s.aml_id));
    }
    get ocultas() {
        return this.state.sugerencias.length - this.sugerenciasVisibles.length;
    }
    get elegidasLista() {
        return Object.entries(this.state.elegidas);
    }
    esElegida(amlId) {
        return Boolean(this.state.elegidas[amlId]);
    }

    // ------------------------------------------------------------------ acciones
    alternarPartida(p) {
        if (this.state.elegidas[p.aml_id]) {
            delete this.state.elegidas[p.aml_id];
            return;
        }
        const resto = Math.max(this.falta, 0);
        const importe = Math.min(p.pendiente, resto || p.pendiente);
        this.state.elegidas[p.aml_id] = { datos: p, importe: Math.round(importe * 100) / 100 };
    }

    agregarRenglon() {
        this.state.renglones.push({
            account_id: false,
            account_name: "",
            importe: Math.max(this.falta, 0),
            name: this.state.actual ? this.state.actual.concepto : "",
        });
    }
    quitarRenglon(i) {
        this.state.renglones.splice(i, 1);
    }
    elegirCuenta(r, texto) {
        const cuenta = this.state.cuentas.find((c) => c.name === texto);
        r.account_name = texto;
        r.account_id = cuenta ? cuenta.id : false;
    }

    async buscarPartidas() {
        if (!this.state.actualId) {
            return;
        }
        this.state.resultados = await this.orm.call(MODELO, "yg_pantalla_buscar", [
            this.state.actualId, this.state.buscar,
        ]);
    }

    async conciliar() {
        if (!this.cuadra || this.state.ocupado) {
            return;
        }
        if (this.state.renglones.some((r) => !r.account_id)) {
            this.notification.add("Elegí la cuenta de cada renglón a cuenta.", { type: "warning" });
            return;
        }
        this.state.ocupado = true;
        try {
            const partidas = Object.entries(this.state.elegidas).map(([id, e]) => [parseInt(id), parseFloat(e.importe)]);
            const imputaciones = this.state.renglones.map((r) => ({
                account_id: r.account_id, importe: parseFloat(r.importe), name: r.name,
            }));
            const proxima = await this.orm.call(MODELO, "yg_pantalla_conciliar", [
                this.state.actualId, partidas, imputaciones, this.state.observacion,
                this.state.renglones.length ? this.state.reglaId : false,
            ]);
            this.notification.add("Movimiento conciliado.", { type: "success" });
            await this.cargar(proxima || false);
        } finally {
            this.state.ocupado = false;
        }
    }

    async deshacer() {
        if (!this.state.actual || !this.state.actual.conciliado) {
            return;
        }
        await this.orm.call(MODELO, "yg_pantalla_deshacer", [this.state.actualId]);
        this.notification.add("Conciliación deshecha: el movimiento volvió a pendiente.", { type: "info" });
        await this.cargar(this.state.actualId);
    }

    async aplicarReglas() {
        const r = await this.orm.call(MODELO, "yg_pantalla_aplicar_reglas", [this.state.journalId]);
        this.notification.add(`Conciliados por regla: ${r.aplicadas}. Quedan pendientes: ${r.pendientes}.`, { type: "info" });
        await this.cargar();
    }

    async cambiarFiltro(filtro) {
        this.state.filtro = filtro;
        await this.cargar();
    }
    async buscarMovimientos() {
        await this.cargar();
    }

    async importarExtracto() {
        try {
            const accion = await this.orm.call("account.journal", "action_yg_import_statement", [[this.state.journalId]]);
            await this.actionService.doAction(accion, { onClose: () => this.cargar() });
        } catch {
            this.notification.add("Para importar desde acá hace falta «Importación de extractos bancarios».", { type: "warning" });
        }
    }

    verLista() {
        return this.actionService.doAction({
            type: "ir.actions.act_window",
            name: `Conciliación bancaria — ${this.state.journal.name}`,
            res_model: MODELO,
            views: [[false, "list"]],
            domain: [["journal_id", "=", this.state.journalId]],
            context: { search_default_pendientes: 1 },
        });
    }

    onTecla(ev) {
        const etiqueta = (ev.target.tagName || "").toLowerCase();
        if (["input", "textarea", "select"].includes(etiqueta)) {
            return;
        }
        const i = this.state.lineas.findIndex((l) => l.id === this.state.actualId);
        if (ev.key === "ArrowDown" && i < this.state.lineas.length - 1) {
            ev.preventDefault();
            this.elegir(this.state.lineas[i + 1].id);
        } else if (ev.key === "ArrowUp" && i > 0) {
            ev.preventDefault();
            this.elegir(this.state.lineas[i - 1].id);
        } else if (ev.key === "Enter" && this.cuadra) {
            ev.preventDefault();
            this.conciliar();
        }
    }
}

registry.category("actions").add("yg_conciliacion_bancaria", YgConciliacionBancaria);

/* MCP UX 2.0 / UX-02. Disabled unless explicitly opted in. */
(function (root) {
    'use strict';
    const namespace = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const instances = new WeakMap();
    function createWorkspace(frm, options) {
        options = options || {};
        if (!frm || (typeof frm !== 'object' && typeof frm !== 'function')) throw new TypeError('Frappe form required');
        if (instances.has(frm)) return instances.get(frm);
        if (!namespace.createStateStore || !namespace.createInteractionController) {
            throw new Error('Load mcp_state_store.js and mcp_interaction_controller.js first');
        }
        const store = namespace.createStateStore();
        const controller = namespace.createInteractionController(store, options);
        let active = false;
        let destroyed = false;
        const workspace = {
            store, controller,
            mount() {
                if (destroyed) throw new Error('Workspace destroyed');
                // UX-02 is strictly headless: no DOM listeners, no Frappe mutations.
                if (options.enabled !== true) return false;
                active = true;
                return true;
            },
            isMounted() { return active; },
            unmount() { active = false; controller.cancel(); },
            destroy() {
                if (destroyed) return;
                this.unmount(); store.destroy(); instances.delete(frm); destroyed = true;
            }
        };
        instances.set(frm, workspace);
        return workspace;
    }
    namespace.createWorkspace = createWorkspace;
})(typeof window !== 'undefined' ? window : globalThis);

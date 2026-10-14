/* MCP UX 2.0 / UX-02. Interaction state only; no incidents or Python calls. */
(function (root) {
    'use strict';
    const namespace = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const ACTIONS = Object.freeze(['Resize', 'Destroy', 'Move', 'Merge', 'Single']);
    const TYPES = Object.freeze({
        Resize: ['finished_good', 'leftover', 'waste'],
        Destroy: ['finished_good', 'leftover', 'waste'],
        Move: ['finished_good'],
        Merge: ['leftover', 'waste'],
        Single: ['leftover', 'waste']
    });
    function createController(store, options) {
        if (!store || typeof store.update !== 'function') throw new TypeError('State store required');
        const allowed = options && options.canApplyAction;
        function permitted(action, type) {
            return ACTIONS.includes(action) && TYPES[action].includes(type) &&
                (!allowed || Boolean(allowed(action, type)));
        }
        function select(node, sheet) {
            const state = store.getState();
            if (state.busy) return false;
            if (!node || !node.id) return false;
            if (state.status === 'selecting_target') return this.addTarget(node);
            store.update({ status: 'selected', action: null, sourceNodeId: String(node.id),
                sourceNodeType: String(node.node_type || ''), selectedSheet: sheet || state.selectedSheet,
                targetNodeIds: [], preview: null, error: null });
            return true;
        }
        function begin(action) {
            const state = store.getState();
            if (state.busy || !state.sourceNodeId || !permitted(action, state.sourceNodeType)) return false;
            store.update({ action, status: ['Move', 'Merge', 'Single'].includes(action)
                ? 'selecting_target' : 'action_active', targetNodeIds: [], preview: null, error: null });
            return true;
        }
        function addTarget(node) {
            const state = store.getState();
            if (state.status !== 'selecting_target' || state.busy || !node || !node.id ||
                String(node.id) === state.sourceNodeId || state.targetNodeIds.includes(String(node.id))) return false;
            store.update({ targetNodeIds: state.targetNodeIds.concat(String(node.id)), error: null });
            return true;
        }
        function showPreview(preview) {
            const state = store.getState();
            if (!state.action || state.busy) return false;
            store.update({ status: 'preview', preview, error: null });
            return true;
        }
        function cancel() {
            if (store.getState().busy) return false;
            store.update({ status: 'idle', action: null, sourceNodeId: null,
                sourceNodeType: null, targetNodeIds: [], preview: null, error: null });
            return true;
        }
        function setError(error) {
            store.update({ status: 'error', busy: false, error: String(error || 'Unknown error') });
        }
        function setBusy(busy) { store.update({ busy: Boolean(busy) }); }
        return { select, begin, addTarget, showPreview, cancel, setError, setBusy,
            canStart: permitted, actions: ACTIONS.slice() };
    }
    namespace.createInteractionController = createController;
})(typeof window !== 'undefined' ? window : globalThis);

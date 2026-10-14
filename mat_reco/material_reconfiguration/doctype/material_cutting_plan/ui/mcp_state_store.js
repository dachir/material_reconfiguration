/* MCP UX 2.0 / UX-02. No mutation of Frappe documents. */
(function (root) {
    'use strict';
    const namespace = root.MatRecoMCPUX20 = root.MatRecoMCPUX20 || {};
    const INITIAL = Object.freeze({
        status: 'idle', action: null, selectedSheet: null,
        sourceNodeId: null, targetNodeIds: [], preview: null,
        busy: false, error: null
    });
    function copy(value) {
        if (Array.isArray(value)) return value.map(copy);
        if (value && typeof value === 'object') {
            const object = {};
            Object.keys(value).forEach(key => { object[key] = copy(value[key]); });
            return object;
        }
        return value;
    }
    function createStore(initial) {
        let state = copy(Object.assign({}, INITIAL, initial || {}));
        const subscribers = new Set();
        let destroyed = false;
        return {
            getState: function () { return copy(state); },
            subscribe: function (listener) {
                if (destroyed) throw new Error('MCP UX state store destroyed');
                if (typeof listener !== 'function') throw new TypeError('Expected listener');
                subscribers.add(listener);
                return () => subscribers.delete(listener);
            },
            update: function (changes) {
                if (destroyed) throw new Error('MCP UX state store destroyed');
                const next = typeof changes === 'function' ? changes(copy(state)) : changes;
                if (!next || typeof next !== 'object' || Array.isArray(next)) throw new TypeError('Expected state changes');
                state = Object.assign({}, state, copy(next));
                const snapshot = copy(state);
                subscribers.forEach(listener => listener(copy(snapshot)));
                return snapshot;
            },
            reset: function () { return this.update(copy(INITIAL)); },
            destroy: function () { subscribers.clear(); destroyed = true; }
        };
    }
    namespace.createStateStore = createStore;
    namespace.initialState = copy(INITIAL);
})(typeof window !== 'undefined' ? window : globalThis);

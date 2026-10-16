import {test} from 'node:test';
import assert from 'node:assert/strict';
import {compositionThickness} from '../src/technical-thickness.js';
const cut={item_type:'DECOUPE',qty_factor:2,children:[{item_type:'PRIMAIRE',thickness_mm:6,qty_factor:99}]};
test('double glazing includes air once and each pane, without multiplying by the raw-source ratio',()=>{
 assert.equal(compositionThickness({item_type:'OUVRAGE',air_gap_mm:12,children:[cut]}),24);
});
test('nested works and accessories preserve thickness',()=>{
 assert.equal(compositionThickness({item_type:'OUVRAGE',children:[{item_type:'OUVRAGE',qty_factor:2,air_gap_mm:12,children:[cut]},{item_type:'ACCESSOIRE',qty_factor:4}]}),48);
});
test('incomplete composition has no misleading thickness result',()=>{
 assert.equal(compositionThickness({item_type:'OUVRAGE',children:[]}),null);
 assert.equal(compositionThickness({item_type:'DECOUPE',children:[]}),null);
});

test('air component contributes thickness and its parent ratio',()=>{
 assert.equal(compositionThickness({item_type:'OUVRAGE',children:[cut,{item_type:'AIR',thickness_mm:12,qty_factor:1}]}),24);
});

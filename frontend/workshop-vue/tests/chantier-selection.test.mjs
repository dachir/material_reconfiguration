import {test} from 'node:test';
import assert from 'node:assert/strict';
import {assignmentIds} from '../src/chantier-selection.js';
test('sans sélection : seulement la ligne cliquée',()=>assert.deepEqual(assignmentIds([], 'A'),['A']));
test('sélection prioritaire même si la ligne cliquée est ailleurs',()=>assert.deepEqual(assignmentIds(['A','B'],'C'),['A','B']));
test('sélection masquée et sélection courante conservées',()=>{const checked=['A','B'];const targets=assignmentIds(checked,'B');targets.push('C');assert.deepEqual(checked,['A','B']);});

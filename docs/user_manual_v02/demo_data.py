from copy import deepcopy
import json
from blueprint import *
from mat_reco.material_reconfiguration.services.mcp_action_preview import preview_intentions
from mat_reco.material_reconfiguration.services.mcp_compensation_service import propose_compensation
initial={'options':{'allow_rotation':False,'kerf_mm':0},'nodes':[{'id':'PLAQUE-DEMO-001','serial_no':'PLAQUE-DEMO-001','node_type':'input_serial','item_code':'VERRE-CLAIR-6MM','thickness_mm':6,'length_mm':3210,'width_mm':2000,'children':[]}]}
for i in range(4):initial['nodes'][0]['children'].append({'id':f'P{i+1}','piece_uid':f'unite-{i+1}','piece_item_code':'DECOUPE-6MM','sales_order':'SO-DEMO-001','node_type':'finished_good','x':i*800,'y':0,'length_mm':800,'width_mm':600,'thickness_mm':6,'rotation':False})
initial['nodes'][0]['children'] += [{'id':'CHUTE-INTERNE','node_type':'leftover','x':0,'y':600,'length_mm':3210,'width_mm':1400},{'id':'BANDE-DECHET','node_type':'waste','x':3200,'y':0,'length_mm':10,'width_mm':600}]
broken_nodes,incidents=preview_intentions(initial['nodes'],[{'action':'Destroy','source_node_id':'P2'}],allow_rotation=True)
broken={**initial,'nodes':broken_nodes};need={'piece_uid':'unite-2','requirement_id':'unite-2','piece_item_code':'DECOUPE-6MM','sales_order':'SO-DEMO-001','length_mm':800,'width_mm':600,'thickness_mm':6,'broken_operation_ids':['P2'],'compensation_qty':1}
stock_l={'serial_no':'CHUTE-STOCK-DEMO-001','item_code':'VERRE-CLAIR-6MM','warehouse':'MATIERE-DEMO','company':'SOCIETE-DEMO','length_mm':600,'width_mm':800,'area_mm2':480000,'thickness_mm':6,'material_status':'Partial','priority':2,'origin':'stock_leftover','compatible':True,'status':'Disponible'}
stock_f={**stock_l,'serial_no':'PLAQUE-DEMO-002','length_mm':3210,'width_mm':2000,'area_mm2':6420000,'material_status':'Full','priority':3,'origin':'stock_sheet'}
version={'signature':'demo-in-memory','modified':'2026-10-14'}
def loaded(tree):return {'valid':True,'effective_tree':tree,'document_version':version,'requirements':[{'piece_uid':'unite-2','operations':[]}],'compensation_requirements':[need],'broken_pieces':[broken_nodes[0]['children'][1]],'replacement_pieces':[],'internal_candidates':[],'stock_candidates':[stock_l,stock_f],'summary':{'requested':4,'valid':3,'broken':1,'to_compensate':1},'warnings':[]}
def preview(tree,sources):
 r=propose_compensation(tree,[need],sources,allow_rotation=True,seed='manual-v02')
 r.update(valid=True,document_version=version,proposal_id='demo-'+str(len(sources)),options={'strategy':'automatic','selected_sources':[],'override_reason':''})
 return r
internal=preview(broken,[stock_l,stock_f]);load_internal=loaded(broken);load_internal['internal_candidates']=internal['internal_candidates']
blocked=deepcopy(broken)
for n in blocked['nodes'][0]['children']:
 if n['id']=='CHUTE-INTERNE':n['node_type']='waste';n['label']='Matière non conservable — scénario de stock'
stock_preview=preview(blocked,[stock_l,stock_f]);full_preview=preview(blocked,[stock_f]);unavailable=preview(blocked,[])
load_stock=loaded(blocked);load_stock['internal_candidates']=stock_preview['internal_candidates']
replacement=internal['placements'][0]['id'];repeat_nodes,repeat_rows=preview_intentions(internal['effective_tree']['nodes'],[{'action':'Destroy','source_node_id':replacement}],allow_rotation=True)
repeat={**internal['effective_tree'],'nodes':repeat_nodes};load_repeat=loaded(repeat);load_repeat['broken_pieces'] += [next(c for n in repeat_nodes for c in n['children'] if c['id']==replacement)]
move_tree=deepcopy(initial);move_tree['nodes'].append({'id':stock_l['serial_no'],'serial_no':stock_l['serial_no'],'node_type':'input_serial','item_code':'VERRE-CLAIR-6MM','thickness_mm':6,'length_mm':600,'width_mm':800,'children':[{'id':'CIBLE-ROTATION','node_type':'leftover','x':0,'y':0,'length_mm':600,'width_mm':800}]})
l_tree={'nodes':[{'id':'CHUTE-DEMO-L','serial_no':'CHUTE-DEMO-L','node_type':'input_serial','length_mm':1800,'width_mm':1500,'children':[{'id':'PIECE-L','node_type':'finished_good','x':0,'y':0,'length_mm':1500,'width_mm':1000},{'id':'CHUTE-L','node_type':'leftover','x':0,'y':1000,'length_mm':1500,'width_mm':500},{'id':'DONNEUR','node_type':'waste','x':1500,'y':0,'length_mm':300,'width_mm':1500}]}]}
values={'initial':initial,'broken':broken,'move_tree':move_tree,'l_tree':l_tree,'internal':internal,'stock_preview':stock_preview,'full_preview':full_preview,'unavailable':unavailable,'loaded':load_internal,'loaded_stock':load_stock,'loaded_repeat':load_repeat,'incidents':incidents}
(OUT/'edition/Scenarios-demonstration-v0.2.json').write_text(json.dumps(values,ensure_ascii=False,indent=2))
print('Demo scenarios validated by real Python geometry; no database operations.')

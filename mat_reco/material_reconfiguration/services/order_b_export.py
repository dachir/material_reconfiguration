"""Traceable commercial CSV exchange package; no customer ledger is posted."""
import csv
import hashlib
import io
import zipfile

import frappe
from frappe.utils import now_datetime,flt
from .order_b_stock import get_order,is_complete

FIELDS=('custom_ug_b_export_file','custom_ug_b_exported_on','custom_ug_b_exported_by','custom_ug_b_sage_reference')


def validate_order(doc,method=None):
    previous=doc.get_doc_before_save()
    if any((doc.get(field) or None)!=((previous.get(field) or None) if previous else None) for field in FIELDS):
        frappe.throw('Utiliser les actions Export Sage B et Confirmer l’import pour modifier le suivi Sage.')


def _csv(columns,rows):
    output=io.StringIO(newline='')
    writer=csv.writer(output,delimiter=';',lineterminator='\r\n')
    writer.writerow(columns);writer.writerows(rows)
    return output.getvalue().encode('utf-8-sig')


def package(order):
    """Separate headers, detail and taxes avoid repeating totals during an import."""
    customer=frappe.get_doc('Customer',order.customer)
    files={}
    files['commandes.csv']=_csv(['Commande','Date','ClientERPNext','NomClient','Devise','Societe','Chantier','TotalBrut','RemiseGlobale','TotalHT','Taxes','TotalTTC'],[
        [order.name,order.transaction_date,order.customer,customer.customer_name,order.currency,order.company,order.custom_chantier,
         order.total,order.discount_amount,order.net_total,order.total_taxes_and_charges,order.grand_total]])
    files['lignes.csv']=_csv(['Commande','IdentifiantLigne','Ordre','Article','Designation','Quantite','Unite','PrixBrut','RemisePourcent','PrixNet','MontantNetHT','LongueurMM','HauteurMM','EpaisseurMM','TypeOuvrage','ParentLigne','UniteTarif','QuantiteTarif','PrixTarifSaisi','SurfaceUnitaireM2'],[
        [order.name,r.name,r.idx,r.item_code,r.item_name,r.qty,r.uom,r.price_list_rate,r.discount_percentage,r.net_rate,r.net_amount,
         r.custom_client_length_mm,r.custom_client_width_mm,r.custom_client_thickness_mm,r.custom_ug_work_type,r.get('custom_parent_row') or '',
         'M2' if r.get('custom_ug_price_per_sqm') else r.uom,
         flt(r.qty)*flt(r.get('custom_ug_pricing_surface')) if r.get('custom_ug_price_per_sqm') else r.qty,
         r.get('custom_ug_pricing_rate') if r.get('custom_ug_price_per_sqm') else r.price_list_rate,r.get('custom_ug_pricing_surface') or ''] for r in order.items])
    files['taxes.csv']=_csv(['Commande','Ordre','Description','ModeCalcul','CompteERPNext','Taux','MontantApresRemise'],[
        [order.name,t.idx,t.description,t.charge_type,t.account_head,t.rate,t.tax_amount_after_discount_amount] for t in order.taxes])
    movements=frappe.db.sql('''SELECT s.name,s.posting_date,d.custom_sales_order_item,d.item_code,d.qty,d.uom,d.serial_no,d.serial_and_batch_bundle
        FROM `tabStock Entry` s JOIN `tabStock Entry Detail` d ON d.parent=s.name
        WHERE s.custom_ug_b_sales_order=%s AND s.docstatus=1 ORDER BY s.posting_date,s.name,d.idx''',order.name,as_dict=True)
    from .workshop_service import _serials
    files['sorties.csv']=_csv(['Commande','Sortie','Date','LigneCommande','Article','QuantiteStock','UniteStock','Series'],[
        [order.name,r.name,r.posting_date,r.custom_sales_order_item,r.item_code,r.qty,r.uom,' | '.join(_serials(r))] for r in movements])
    files['README.txt']=('ECHANGE COMMERCIAL CIRCUIT B - VERSION 1\n'
        'CSV UTF-8 avec BOM ; séparateur point-virgule ; décimales avec point.\n'
        'Clé commande : Commande. Clé ligne : Commande + IdentifiantLigne.\n'
        'Les en-têtes, lignes, taxes et sorties sont séparés pour éviter de cumuler plusieurs fois les totaux.\n'
        'Les montants sont exprimés dans la devise de la commande. Les quantités physiques sont dans sorties.csv.\n'
        'PrixNet et MontantNetHT sont après remises : ne pas appliquer une seconde fois les remises informatives.\n'
        'Les colonnes UniteTarif, QuantiteTarif et PrixTarifSaisi conservent le choix commercial PC/M2.\n'
        'TVA et AIRSI figurent dans taxes.csv uniquement lorsqu’elles existent sur la commande.\n'
        'Les codes clients/articles ERPNext doivent être rapprochés des codes Sage.\n'
        'Ce format d’échange proposé nécessite un mapping vers le modèle d’import Sage 100 du client.\n'
        'Il ne constitue pas un fichier d’écritures comptables Sage standard.\n'
        'Ne pas réimporter une commande déjà intégrée. Confirmer la référence Sage dans ERPNext après contrôle.\n').encode('utf-8')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,content in files.items():archive.writestr(name,content)
    return output.getvalue()


@frappe.whitelist(methods=['POST'])
def export_order(sales_order):
    order=get_order(sales_order,write=True)
    if order.custom_ug_b_export_file:
        file=frappe.get_doc('File',order.custom_ug_b_export_file);file.check_permission('read')
        return dict(file=file.name,file_url=file.file_url)
    if not order.custom_technical_study or frappe.db.get_value('Chantier Technical Study',order.custom_technical_study,'docstatus')!=1:
        frappe.throw('Valider la fiche technique avant l’export commercial B.')
    if not is_complete(order):frappe.throw('Terminer les sorties physiques avant l’export commercial B.')
    content=package(order)
    from frappe.utils.file_manager import save_file
    file=save_file('Echange-Sage-B-'+order.name+'.zip',content,'Sales Order',order.name,is_private=1)
    stamp=now_datetime()
    frappe.db.set_value('Sales Order',order.name,dict(custom_ug_b_export_file=file.name,custom_ug_b_exported_on=stamp,custom_ug_b_exported_by=frappe.session.user))
    order.add_comment('Info','Export commercial B généré : '+frappe.utils.escape_html(file.name)+' ; SHA-256 : '+hashlib.sha256(content).hexdigest())
    from .order_b_stock import refresh_tasks
    refresh_tasks(order.name,'export:'+file.name)
    return dict(file=file.name,file_url=file.file_url)


@frappe.whitelist(methods=['POST'])
def confirm_import(sales_order,sage_reference):
    order=get_order(sales_order,write=True)
    reference=(sage_reference or '').strip()
    if not reference or len(reference)>140:frappe.throw('Référence Sage requise (140 caractères maximum).')
    if order.custom_ug_b_sage_reference:
        if order.custom_ug_b_sage_reference!=reference:frappe.throw('Un import Sage a déjà été confirmé avec une autre référence.')
        return order.name
    if not order.custom_ug_b_export_file or not is_complete(order):frappe.throw('Exporter la commande après ses sorties avant de confirmer l’import Sage.')
    frappe.db.set_value('Sales Order',order.name,'custom_ug_b_sage_reference',reference)
    order.reload();order.update_status('Closed')
    order.add_comment('Info','Import Sage B confirmé : '+frappe.utils.escape_html(reference))
    from .task_notifications import close_tasks
    close_tasks(order,'b_export')
    return order.name


def install():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    fields=[dict(fieldname='custom_ug_b_export_file',label='Export commercial B',fieldtype='Link',options='File'),
        dict(fieldname='custom_ug_b_exported_on',label='Export B généré le',fieldtype='Datetime'),
        dict(fieldname='custom_ug_b_exported_by',label='Export B généré par',fieldtype='Link',options='User'),
        dict(fieldname='custom_ug_b_sage_reference',label='Référence import Sage B',fieldtype='Data')]
    for field in fields:field.update(read_only=1,allow_on_submit=1,no_copy=1,module='Material Reconfiguration',depends_on='eval:doc.custom_ug_order_type=="B"')
    create_custom_fields({'Sales Order':fields},update=True)

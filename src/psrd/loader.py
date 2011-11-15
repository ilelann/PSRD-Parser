import json
from psrd.sql import get_db_connection
from psrd.universal import print_struct
from psrd.sections import cap_words
from psrd.sql import find_section, fetch_top, append_child_section, fetch_section, update_section
from psrd.sql.abilities import insert_ability_type
from psrd.sql.feats import insert_feat_type
from psrd.sql.skills import insert_skill_attribute
from psrd.sql.spells import insert_spell_detail, insert_spell_list, fetch_spell_lists, insert_spell_descriptor, insert_spell_component, fetch_spell_components, insert_spell_effect, fetch_complete_spell, merge_spells

class ProcessLastException(Exception):
	def __init__(self, value):
		self.parameter = value

	def __str__(self):
		return repr(self.parameter)

def fetch_parent(curs, parent_name):
	if not parent_name:
		return fetch_top(curs)
	else:
		find_section(curs, name=parent_name, section_type='list')
		parent = curs.fetchone()
		if parent:
			return parent
		else:
			top = fetch_top(curs)
			section_id = append_child_section(curs, top['section_id'], 'list', None, parent_name, None, 'PFSRD', None, None)
			fetch_section(curs, section_id)
			return curs.fetchone()
		
def load_documents(db, args, parent):
	conn = get_db_connection(db)
	last = []
	for arg in args:
		fp = open(arg, 'r')
		struct = json.load(fp)
		fp.close()
		try:
			load_document(db, conn, arg, struct, parent)
		except ProcessLastException, pe:
			conn.rollback()
			last.append((struct, arg))
	for struct, arg in last:
		load_document(db, conn, arg, struct, parent)

def load_document(db, conn, filename, struct, parent):
	curs = conn.cursor()
	try:
		top = fetch_parent(curs, parent)
		section_id = insert_section(curs, top['section_id'], struct)
		conn.commit()
	finally:
		curs.close()
	print_struct(struct)

def insert_section(curs, parent_id, section):
	sec_id = append_child_section(curs, parent_id, section['type'], section.get('subtype'), section.get('name'), section.get('abbrev'), section.get('source'), section.get('description'), section.get('text'))
	section['section_id'] = sec_id
	insert_subrecords(curs, section, sec_id)
	for s in section.get('sections', []):
		insert_section(curs, sec_id, s)
	return sec_id

def insert_subrecords(curs, section, section_id):
	if section['type'] == 'feat':
		if section.has_key('feat_types'):
			for feat_type in section['feat_types']:
				insert_feat_type(curs, section_id, feat_type)
		else:
			insert_feat_type(curs, section_id, 'General')
	elif section['type'] == 'skill':
		insert_skill_attribute(curs, section_id, attribute=section['attribute'], armor_check_penalty=section.get('armor_check_penalty'), trained_only=section.get('trained_only'))
	elif section['type'] == 'ability':
		for ability_type in section['ability_types']:
			insert_ability_type(curs, section_id, ability_type)
	elif section['type'] == 'spell':
		insert_spell_records(curs, section_id, section)

def insert_spell_records(curs, section_id, spell):
	if spell.has_key('parent'):
		orig = fetch_complete_spell(curs, spell['parent'])
		if not orig:
			raise ProcessLastException(spell['parent'])
		spell = merge_spells(orig, spell)
	insert_spell_detail(curs, section_id, spell.get('school'), spell.get('subschool'), spell.get('casting_time'), spell.get('preparation_time'), spell.get('range'), spell.get('duration'), spell.get('saving_throw'), spell.get('spell_resistance'), spell.get('as_spell_id'))
	for level in spell.get('level', []):
		magic_type = find_magic_type(level['class'])
		insert_spell_list(curs, section_id, level['level'], level['class'], magic_type)
	for component in spell.get('components', []):
		insert_spell_component(curs, section_id, component['type'], component.get('text'), 0)
	for descriptor in spell.get('descriptor', []):
		insert_spell_descriptor(curs, section_id, descriptor)
	for effect in spell.get('effects', []):
		insert_spell_effect(curs, section_id, effect['name'], effect['text'])

def find_magic_type(class_name):
	magic_type = 'arcane'
	if class_name.lower() in ['cleric', 'druid', 'parladin', 'ranger', 'oracle', 'inquisitor']:
		magic_type = 'divine'
	return magic_type

def load_spell_list_documents(db, args, parent):
	conn = get_db_connection(db)
	last = []
	for arg in args:
		fp = open(arg, 'r')
		struct = json.load(fp)
		fp.close()
		try:
			load_spell_list_document(db, conn, arg, struct, parent)
		except ProcessLastException, pe:
			conn.rollback()
			last.append((struct, arg))
	for struct, arg in last:
		load_document(db, conn, arg, struct, parent)

def load_spell_list_document(db, conn, filename, struct, parent):
	curs = conn.cursor()
	try:
		section_id = add_spell_list(curs, struct)
		conn.commit()
	finally:
		curs.close()
	print_struct(struct)

def add_spell_list(curs, struct):
	if not struct['type'] == 'spell_list':
		raise Exception("This should only be run on spell list files")
	if struct['class'] in ("Sorcerer/wizard", "Sorcerer/Wizard"):
		struct['class'] = "Sorcerer"
		add_spell_list(curs, struct)
		struct['class'] = "Wizard"
		add_spell_list(curs, struct)
		return
	struct = fix_spell_list(struct)
	level = struct['level']
	class_name = cap_words(struct['class'])
	for sp in struct['spells']:
		name = cap_words(sp['name']).strip()
		find_section(curs, name=name, section_type='spell')
		spell = curs.fetchone()
		if not spell:
			raise Exception("Cannot find spell %s" % sp['name'])
		fetch_spell_lists(curs, spell['section_id'], class_name=class_name)
		if not curs.fetchone():
			magic_type = find_magic_type(class_name.lower())
			insert_spell_list(curs, spell['section_id'], level, class_name, magic_type)
		update_section(curs, spell['section_id'], description=sp['description'])

def fix_spell_list(struct):
	spells = struct['spells']
	newspells = []
	for spell in spells:
		if spell['name'].find("Chaos/Evil/Good/Law") > -1:
			name = spell['name'].replace("Chaos/Evil/Good/Law", "")
			newspells.append({'name': name + "Chaos", "description": spell['description']})
			newspells.append({'name': name + "Evil", "description": spell['description']})
			newspells.append({'name': name + "Good", "description": spell['description']})
			newspells.append({'name': name + "Law", "description": spell['description']})
		elif spell['name'].find("Chaos/Evil") > -1:
			name = spell['name'].replace("Chaos/Evil", "")
			newspells.append({'name': name + "Chaos", "description": spell['description']})
			newspells.append({'name': name + "Evil", "description": spell['description']})
		elif spell['name'].find("Good/Law") > -1:
			name = spell['name'].replace("Good/Law", "")
			newspells.append({'name': name + "Good", "description": spell['description']})
			newspells.append({'name': name + "Law", "description": spell['description']})
		elif spell['name'] == "Thunderous Drums":
			newspells.append({'name': "Thundering Drums", "description": spell['description']})
		elif spell['name'] == "PlanarBinding, Lesser":
			newspells.append({'name': "Planar Binding, Lesser", "description": spell['description']})
		elif spell['name'] == "PlanarBinding, Greater":
			newspells.append({'name': "Planar Binding, Greater", "description": spell['description']})
		elif spell['name'] == "Lend Greater Judgment":
			newspells.append({'name': "Lend Judgment, Greater", "description": spell['description']})
		#elif spell['name'] == "Ghoul Touch":
		#	newspells.append({'name': "Ghoul touch", "description": spell['description']})
		#elif spell['name'] == "Vampiric Touch":
		#	newspells.append({'name': "Vampiric touch", "description": spell['description']})
		#elif spell['name'] == "Protection From Energy":
		#	newspells.append({'name': "Protection from Energy", "description": spell['description']})
		#elif spell['name'] == "Marks of Forbiddance":
		#	newspells.append({'name': "Marks Of Forbiddance", "description": spell['description']})
		#elif spell['name'] == "Silk to Steel":
		#	newspells.append({'name': "Silk To Steel", "description": spell['description']})
		#elif spell['name'] == "Ride the Waves":
		#	newspells.append({'name': "Ride The Waves", "description": spell['description']})
		#elif spell['name'] == "Transmute Blood to Acid":
		#	newspells.append({'name': "Transmute Blood To Acid", "description": spell['description']})
		elif spell['name'] in ("Vermin Shape II", "Interrogation, Greater", "Lightning Rod"): # This is really fucked up, get ot it later.
			pass
		else:
			newspells.append(spell)
	struct['spells'] = newspells
	return struct


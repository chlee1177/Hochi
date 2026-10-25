extends Control

const Campaign = preload("res://campaign.gd")
const Battlefield = preload("res://battlefield.gd")
var campaign = Campaign.new()
var actor = 0
var target = 0
var layout: VBoxContainer
var save_path = "user://campaign.json"
var scroll: ScrollContainer

func _ready():
	var theme = Theme.new()
	var font = SystemFont.new()
	font.font_names = PackedStringArray(["Noto Sans CJK KR", "Malgun Gothic", "Apple SD Gothic Neo", "sans-serif"])
	theme.default_font = font
	theme.default_font_size = 17
	self.theme = theme
	scroll = ScrollContainer.new()
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scroll.offset_left = 32
	scroll.offset_top = 20
	scroll.offset_right = -32
	scroll.offset_bottom = -20
	add_child(scroll)
	render()

func _draw():
	for index in range(100):
		var point = Vector2(fmod(index * 193.0 + 27, size.x), fmod(index * 127.0 + 14, size.y))
		draw_circle(point, 1.0 if index % 3 else 2.0, Color(0.35, 0.48, 0.65, 0.45))

func label(text, font_size = 18, color = Color("bccbdd")):
	var node = Label.new()
	node.text = text
	node.add_theme_font_size_override("font_size", font_size)
	node.add_theme_color_override("font_color", color)
	return node

func button(text, action, disabled = false):
	var node = Button.new()
	node.text = text
	node.disabled = disabled
	node.custom_minimum_size = Vector2(150, 46)
	node.pressed.connect(action)
	return node

func invoke(method):
	method.call()
	if actor >= campaign.heroes.size() or campaign.heroes[actor].acted or campaign.heroes[actor].hp <= 0:
		for index in range(campaign.heroes.size()):
			if campaign.heroes[index].hp > 0 and not campaign.heroes[index].acted:
				actor = index
				break
	if not campaign.enemies.is_empty() and campaign.enemies[target].hp <= 0:
		for index in range(campaign.enemies.size()):
			if campaign.enemies[index].hp > 0:
				target = index
				break
	render()

func render():
	if is_instance_valid(layout):
		scroll.remove_child(layout)
		layout.queue_free()
	layout = VBoxContainer.new()
	layout.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	layout.add_theme_constant_override("separation", 10)
	scroll.add_child(layout)
	layout.add_child(label("HOCHI / TACTICAL EXPEDITION", 14, Color("73d5cc")))
	var top = HBoxContainer.new()
	top.add_child(label("스페이스 머셔너리", 34, Color("eef2fa")))
	var spacer = Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(spacer)
	top.add_child(label("임무 %02d  ·  %d CR  ·  %s" % [campaign.mission, campaign.credits, "ROUND %d" % campaign.round_number if campaign.phase == "combat" else "기지"], 20))
	layout.add_child(top)
	layout.add_child(label("공허 속에서 살아남는 것은 영웅이 아니라, 함께 돌아오는 용병단이다.", 17))
	var battlefield = Battlefield.new()
	battlefield.campaign = campaign
	battlefield.custom_minimum_size.y = 135
	layout.add_child(battlefield)
	layout.add_child(label("용병 진형  /  왼쪽 두 명: 전열 · 오른쪽 두 명: 후열", 16, Color("73d5cc")))
	var party = HBoxContainer.new()
	party.add_theme_constant_override("separation", 12)
	for index in range(campaign.heroes.size()):
		var hero = campaign.heroes[index]
		var state = "전투 불능" if hero.hp <= 0 else ("행동 완료" if hero.acted and campaign.phase == "combat" else "행동 가능")
		var card = button("%s %s · %s\n\nHP %d / %d\n스트레스 %d / 100\n%s" % ["▶" if actor == index else "◇", hero.name, hero.role, hero.hp, hero.max_hp, hero.stress, state], func(): actor = index; render(), hero.hp <= 0)
		card.custom_minimum_size.y = 125
		card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		party.add_child(card)
	layout.add_child(party)
	layout.add_child(label("조우한 적  /  공격 대상을 선택하세요", 16, Color("e99b82")))
	var hostiles = HBoxContainer.new()
	hostiles.add_theme_constant_override("separation", 12)
	if campaign.phase == "combat":
		for index in range(campaign.enemies.size()):
			var enemy = campaign.enemies[index]
			var card = button("%s %s\nHP %d / %d" % ["◎" if target == index else "◈", enemy.name, enemy.hp, enemy.max_hp], func(): target = index; render(), enemy.hp <= 0)
			card.custom_minimum_size.y = 85
			card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			hostiles.add_child(card)
	else:
		hostiles.add_child(label("정거장 수색을 준비하세요. 치료와 진형 교대 후 출격할 수 있습니다." if campaign.phase == "base" else "용병단 전멸. 새 캠페인을 시작하세요.", 20))
	layout.add_child(hostiles)
	var actions = HBoxContainer.new()
	actions.add_theme_constant_override("separation", 8)
	if campaign.phase == "combat":
		for pair in [["공격", "attack"], ["방어 / 진정", "guard"], ["아군 회복", "heal"]]:
			var action = pair[1]
			actions.add_child(button(pair[0], func(): invoke(func(): campaign.act(actor, action, target)), campaign.heroes[actor].acted or campaign.heroes[actor].hp <= 0))
	else:
		actions.add_child(button("임무 출격", func(): actor = 0; target = 0; invoke(campaign.launch), campaign.phase != "base"))
		actions.add_child(button("전원 치료 · 30 CR", func(): invoke(campaign.recover), campaign.phase != "base" or campaign.credits < 30))
		actions.add_child(button("진형 교대", func(): invoke(campaign.rotate_formation), campaign.phase != "base"))
	actions.add_child(button("저장", save_game, campaign.phase == "combat"))
	actions.add_child(button("불러오기", load_game, campaign.phase == "combat"))
	actions.add_child(button("새 캠페인", confirm_reset))
	layout.add_child(actions)
	layout.add_child(label("전투 기록", 15, Color("73d5cc")))
	var record = label("\n".join(campaign.log_lines), 16)
	record.size_flags_vertical = Control.SIZE_EXPAND_FILL
	layout.add_child(record)
	layout.add_child(label("모든 생존 용병이 행동하면 적 차례가 자동 진행됩니다. 스트레스 100: 공격력 감소. 저장은 기지에서 가능합니다.", 13))

func save_game():
	var file = FileAccess.open(save_path + ".tmp", FileAccess.WRITE)
	if file == null:
		campaign.message("저장 파일을 쓸 수 없습니다.")
	else:
		file.store_string(JSON.stringify(campaign.snapshot()))
		file.close()
		var error = DirAccess.rename_absolute(save_path + ".tmp", save_path)
		campaign.message("캠페인 저장 완료." if error == OK else "저장 파일 교체 실패.")
	render()

func load_game():
	if not FileAccess.file_exists(save_path):
		campaign.message("저장된 캠페인이 없습니다.")
	else:
		var data = JSON.parse_string(FileAccess.get_file_as_string(save_path))
		if not campaign.restore(data): campaign.message("저장 데이터가 올바르지 않습니다.")
	actor = 0
	target = 0
	render()

func confirm_reset():
	var dialog = ConfirmationDialog.new()
	dialog.dialog_text = "진행 중인 캠페인을 초기화할까요? 저장 파일은 유지됩니다."
	add_child(dialog)
	dialog.confirmed.connect(func(): campaign = Campaign.new(); actor = 0; target = 0; render(); dialog.queue_free())
	dialog.canceled.connect(dialog.queue_free)
	dialog.popup_centered()

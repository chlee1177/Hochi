extends RefCounted

var heroes = []
var enemies = []
var mission = 1
var credits = 60
var round_number = 0
var phase = "base"
var log_lines = []
var rng = RandomNumberGenerator.new()

func _init():
	rng.randomize()
	var specs = [["카이", "돌격병", 48, 13], ["레나", "저격수", 34, 17], ["모스", "기술병", 40, 11], ["이브", "의무병", 36, 9]]
	for spec in specs:
		heroes.append({"name": spec[0], "role": spec[1], "max_hp": spec[2], "hp": spec[2], "attack": spec[3], "stress": 0, "shield": false, "acted": false})
	log_lines.append("용병단 결성. 전열은 적에게 자주 노출되고, 후열은 공격력이 20% 감소합니다.")

func message(text):
	log_lines.append(text)
	if log_lines.size() > 8:
		log_lines.pop_front()

func launch():
	if phase != "base": return false
	if heroes.all(func(hero): return hero.hp <= 0): return false
	enemies.clear()
	for index in range(3):
		var hp = 25 + mission * 5 + index * 4
		enemies.append({"name": ["해적 척후병", "공허 드론", "해적 대장"][index], "hp": hp, "max_hp": hp, "attack": 5 + mission * 2})
	phase = "combat"
	round_number = 1
	for hero in heroes:
		hero.acted = false
		hero.shield = false
	message("임무 %d: 폐허 우주 정거장에 진입했습니다." % mission)
	return true

func act(hero_index, action, target_index):
	if phase != "combat" or hero_index < 0 or hero_index >= heroes.size(): return false
	var hero = heroes[hero_index]
	if hero.hp <= 0 or hero.acted: return false
	if action == "attack":
		if target_index < 0 or target_index >= enemies.size() or enemies[target_index].hp <= 0: return false
		var damage = hero.attack + rng.randi_range(-3, 3)
		if hero_index >= 2: damage = int(damage * 0.8)
		if hero.stress >= 100: damage = int(damage * 0.65)
		var target = enemies[target_index]
		target.hp = maxi(0, target.hp - damage)
		hero.stress = mini(100, hero.stress + 4)
		message("%s → %s: %d 피해" % [hero.name, target.name, damage])
	elif action == "guard":
		hero.shield = true
		hero.stress = maxi(0, hero.stress - 12)
		message("%s: 방어 태세, 다음 적 차례 피해 절반. 스트레스 -12" % hero.name)
	elif action == "heal":
		var wounded = heroes.filter(func(unit): return unit.hp > 0)
		wounded.sort_custom(func(a, b): return float(a.hp) / a.max_hp < float(b.hp) / b.max_hp)
		if wounded.is_empty(): return false
		var patient = wounded[0]
		var amount = 12 if hero.role == "의무병" else 5
		patient.hp = mini(patient.max_hp, patient.hp + amount)
		hero.stress = mini(100, hero.stress + 3)
		message("%s → %s: 체력 회복 +%d" % [hero.name, patient.name, amount])
	else:
		return false
	hero.acted = true
	if enemies.all(func(unit): return unit.hp <= 0):
		var reward = 40 + mission * 15
		credits += reward
		mission += 1
		phase = "base"
		for unit in heroes: unit.stress = maxi(0, unit.stress - 8)
		message("임무 성공! %d 크레딧 확보. 기지에서 회복 후 다음 임무를 준비하세요." % reward)
	elif heroes.all(func(unit): return unit.hp <= 0 or unit.acted):
		enemy_turn()
	return true

func enemy_turn():
	for enemy in enemies:
		if enemy.hp <= 0: continue
		var targets = []
		for index in range(heroes.size()):
			if heroes[index].hp > 0:
				targets.append(index)
				if index < 2: targets.append(index)
		if targets.is_empty(): break
		var hero = heroes[targets[rng.randi_range(0, targets.size() - 1)]]
		var damage = enemy.attack + rng.randi_range(0, 3)
		if hero.shield: damage = maxi(1, int(damage / 2.0))
		hero.hp = maxi(0, hero.hp - damage)
		hero.stress = mini(100, hero.stress + 10)
		message("%s → %s: %d 피해%s" % [enemy.name, hero.name, damage, " / 전투 불능" if hero.hp == 0 else ""])
	if heroes.all(func(unit): return unit.hp <= 0):
		phase = "defeat"
		message("용병단 전멸. 새 캠페인으로 다시 시작하세요.")
	else:
		round_number += 1
		for hero in heroes:
			hero.acted = false
			hero.shield = false

func recover():
	if phase != "base" or credits < 30: return false
	credits -= 30
	for hero in heroes:
		hero.hp = hero.max_hp
		hero.stress = maxi(0, hero.stress - 35)
	message("기지 의무실: 전원 치료 및 스트레스 회복. -30 크레딧")
	return true

func rotate_formation():
	if phase != "base": return false
	heroes.push_back(heroes.pop_front())
	message("진형 교대. 왼쪽 두 명이 전열입니다.")
	return true

func snapshot():
	return {"version": 1, "heroes": heroes, "mission": mission, "credits": credits}

func restore(data):
	if not data is Dictionary or data.get("version") != 1: return false
	if not data.get("heroes") is Array or data.heroes.size() != 4: return false
	if not data.get("mission") is float and not data.get("mission") is int: return false
	if not data.get("credits") is float and not data.get("credits") is int: return false
	if data.mission < 1 or data.mission > 10000 or data.credits < 0 or data.credits > 100000000: return false
	var names = []
	for hero in data.heroes:
		if not hero is Dictionary: return false
		for key in ["name", "role"]:
			if not hero.get(key) is String: return false
		for key in ["max_hp", "hp", "stress", "attack"]:
			if not hero.get(key) is float and not hero.get(key) is int: return false
		if hero.name not in ["카이", "레나", "모스", "이브"] or hero.name in names: return false
		names.append(hero.name)
		if hero.max_hp < 1 or hero.max_hp > 100 or hero.hp < 0 or hero.hp > hero.max_hp: return false
		if hero.stress < 0 or hero.stress > 100 or hero.attack < 1 or hero.attack > 50: return false
		if not hero.get("shield") is bool or not hero.get("acted") is bool: return false
	heroes = data.heroes.duplicate(true)
	mission = int(data.mission)
	credits = int(data.credits)
	phase = "base" if heroes.any(func(unit): return unit.hp > 0) else "defeat"
	enemies.clear()
	message("캠페인을 불러왔습니다.")
	return true

extends SceneTree
const Campaign = preload("res://campaign.gd")

func check(condition, text):
	if not condition:
		push_error(text)
		quit(1)
		return false
	print("PASS ", text)
	return true

func _init():
	var game = Campaign.new()
	game.rng.seed = 42
	if not check(game.heroes.size() == 4 and game.launch(), "four mercenaries launch"): return
	if not check(game.act(0, "guard", 0) and not game.act(0, "attack", 0), "one action per round"): return
	for index in [1, 2, 3]: game.act(index, "guard", 0)
	if not check(game.round_number == 2 and game.heroes.any(func(hero): return hero.hp < hero.max_hp), "enemy turn deals damage"): return
	game.enemies = [{"name": "test", "hp": 1, "max_hp": 1, "attack": 1}]
	var before = game.credits
	if not check(game.act(0, "attack", 0) and game.phase == "base" and game.credits > before and game.mission == 2, "victory rewards and progression"): return
	if not check(game.recover() and game.heroes.all(func(hero): return hero.hp == hero.max_hp), "base recovery"): return
	var restored = Campaign.new()
	if not check(restored.restore(JSON.parse_string(JSON.stringify(game.snapshot()))) and restored.mission == 2, "save round trip"): return
	if not check(not restored.restore({"version": 1, "heroes": []}), "invalid save rejected"): return
	game.launch()
	for hero in game.heroes: hero.hp = 1
	for enemy in game.enemies: enemy.attack = 999
	for index in range(4): game.act(index, "guard", 0)
	# Three enemies can leave one survivor, so continue until all are dead.
	for turn in range(4):
		if game.phase != "combat": break
		for index in range(4): game.act(index, "guard", 0)
	if not check(game.phase == "defeat", "party wipe ends campaign"): return
	print("8 campaign checks passed")
	quit(0)

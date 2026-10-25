extends SceneTree

func _init():
	call_deferred("run")

func find_button(node, text):
	if node is Button and node.text == text: return node
	for child in node.get_children():
		var found = find_button(child, text)
		if found != null: return found
	return null

func fail(text):
	push_error(text)
	quit(1)

func run():
	var game = load("res://main.tscn").instantiate()
	root.add_child(game)
	await process_frame
	find_button(game, "임무 출격").pressed.emit()
	await process_frame
	if game.campaign.phase != "combat": fail("Launch button failed"); return
	var selected = false
	for child in game.layout.get_children():
		if child is HBoxContainer and child.get_child_count() == 4 and child.get_child(0) is Button:
			child.get_child(3).pressed.emit()
			selected = true
			break
	await process_frame
	if not selected or game.actor != 3: fail("Actor selection button failed"); return
	var before = game.campaign.enemies[0].hp
	find_button(game, "공격").pressed.emit()
	await process_frame
	if not game.campaign.heroes[3].acted or game.campaign.enemies[0].hp >= before: fail("Attack button failed"); return
	print("PASS game UI: launch → choose fourth mercenary → attack → damage and action recorded")
	game.queue_free()
	await process_frame
	quit(0)

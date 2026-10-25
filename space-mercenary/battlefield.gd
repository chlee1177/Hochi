extends Control

var campaign

func _draw():
	draw_style_box(panel(), Rect2(Vector2.ZERO, size))
	for index in range(30):
		draw_circle(Vector2(fmod(index * 79.0 + 20, size.x), fmod(index * 47.0 + 10, size.y - 30)), 1.2, Color("687a98"))
	draw_line(Vector2(24, size.y - 22), Vector2(size.x - 24, size.y - 22), Color("51637b"), 2)
	if campaign == null: return
	for index in range(4):
		var hero = campaign.heroes[index]
		var point = Vector2(size.x * (0.08 + index * 0.105), size.y - 45)
		var color = [Color("75d7d0"), Color("af94ec"), Color("e6b567"), Color("87b9ed")][index]
		if hero.hp <= 0: color = Color("50596c")
		draw_circle(point + Vector2(0, -38), 13, color)
		draw_rect(Rect2(point + Vector2(-9, -48), Vector2(18, 9)), Color("13243e"))
		draw_rect(Rect2(point + Vector2(-13, -22), Vector2(26, 26)), color)
		draw_line(point + Vector2(-7, 4), point + Vector2(-12, 20), color, 7)
		draw_line(point + Vector2(7, 4), point + Vector2(12, 20), color, 7)
		draw_line(point + Vector2(12, -14), point + Vector2(31, -8), color, 6)
		draw_rect(Rect2(point + Vector2(23, -16), Vector2(23, 7)), Color("bed2e3"))
		draw_rect(Rect2(point + Vector2(-24, 28), Vector2(48, 4)), Color("27344d"))
		draw_rect(Rect2(point + Vector2(-24, 28), Vector2(48.0 * hero.hp / hero.max_hp, 4)), color)
	if campaign.phase == "combat":
		for index in range(campaign.enemies.size()):
			var enemy = campaign.enemies[index]
			var point = Vector2(size.x * (0.67 + index * 0.11), size.y * 0.5)
			var color = Color("ec8c79") if enemy.hp > 0 else Color("50596c")
			draw_colored_polygon(PackedVector2Array([point + Vector2(-26, 0), point + Vector2(0, -23), point + Vector2(26, 0), point + Vector2(0, 23)]), color)
			draw_circle(point, 8, Color("2b1830"))
			draw_line(point + Vector2(-40, -8), point + Vector2(-28, 8), color, 5)
			draw_line(point + Vector2(28, 8), point + Vector2(40, -8), color, 5)
			draw_rect(Rect2(point + Vector2(-25, 34), Vector2(50.0 * enemy.hp / enemy.max_hp, 4)), color)

func panel():
	var style = StyleBoxFlat.new()
	style.bg_color = Color("101a2c")
	style.set_corner_radius_all(8)
	return style

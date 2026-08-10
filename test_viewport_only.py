"""Tests for the viewport-only MCP surface and camera-code guard."""

import pathlib

import pytest

from blender_mcp import server
from blender_mcp.server import execute_blender_code, mcp, validate_camera_view_code


def test_only_two_mcp_tools_are_exposed():
    tool_names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert tool_names == {"get_viewport_screenshot", "execute_blender_code"}


def test_legacy_interfaces_are_removed():
    root = pathlib.Path(__file__).parent
    server_source = (root / "src/blender_mcp/server.py").read_text()
    addon_source = (root / "addon.py").read_text()
    for legacy_name in (
        "get_scene_info",
        "get_object_info",
        "get_polyhaven_status",
        "search_sketchfab_models",
        "generate_hyper3d_model_via_text",
        "generate_hunyuan3d_model",
        "asset_creation_strategy",
    ):
        assert f"def {legacy_name}" not in server_source
        assert f"def {legacy_name}" not in addon_source


def test_addon_routes_validated_code_to_the_actual_exec_handler():
    addon_source = (pathlib.Path(__file__).parent / "addon.py").read_text()
    assert '"execute_code": self.execute_code' in addon_source
    assert "exec(code, namespace)" in addon_source


def test_mcp_tool_validates_before_sending_code_to_blender(monkeypatch):
    commands = []

    class FakeConnection:
        def send_command(self, command, params):
            commands.append((command, params))
            return {"result": ""}

    monkeypatch.setattr(server, "get_blender_connection", lambda: FakeConnection())
    tool = execute_blender_code.__wrapped__
    allowed = """import bpy
area = bpy.context.area
area.spaces.active.shading.type = "RENDERED"
area.tag_redraw()
"""
    assert tool(None, allowed).startswith("Code executed successfully")
    assert commands == [("execute_code", {"code": allowed})]

    commands.clear()
    result = tool(None, "import bpy\nbpy.data.objects.clear()")
    assert result.startswith("Error executing code:")
    assert "call to 'bpy.data.objects.clear' is not allowed" in result
    assert commands == []


@pytest.mark.parametrize(
    "code",
    [
        """import bpy
camera = bpy.context.scene.camera
camera.location = (1.0, 2.0, 3.0)
camera.rotation_euler = (0.1, 0.2, 0.3)
camera.data.lens = 50
""",
        """import bpy
from mathutils import Vector
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        region_3d = area.spaces.active.region_3d
        region_3d.view_location = Vector((0.0, 0.0, 0.0))
        region_3d.view_distance = 8.0
        region_3d.view_perspective = 'CAMERA'
        region_3d.update()
""",
    ],
)
def test_camera_view_changes_are_allowed(code):
    validate_camera_view_code(code)


def test_rendered_shading_example_is_allowed():
    validate_camera_view_code("""import bpy
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        space = area.spaces.active
        space.shading.type = "RENDERED"
        area.tag_redraw()
        break
""")


@pytest.mark.parametrize("shading_type", ["SOLID", "MATERIAL", "RENDERED"])
def test_supported_viewport_shading_types_are_allowed(shading_type):
    validate_camera_view_code(f"""import bpy
area = bpy.context.area
space = area.spaces.active
space.shading.type = {shading_type!r}
area.tag_redraw()
""")


@pytest.mark.parametrize("show_overlays", [False, True])
def test_overlay_toggle_is_allowed(show_overlays):
    validate_camera_view_code(f"""import bpy
space = bpy.context.space_data
space.overlay.show_overlays = {show_overlays!r}
bpy.context.area.tag_redraw()
""")


def test_region_view_state_and_aliases_are_allowed():
    validate_camera_view_code("""import bpy
from mathutils import Quaternion, Vector

screen = bpy.context.screen
for area in screen.areas:
    if area.type == "VIEW_3D":
        spaces = area.spaces
        space = spaces.active
        r3d = space.region_3d
        r3d.view_location = Vector((1.0, 2.0, 3.0))
        r3d.view_distance = 7.5
        r3d.view_rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
        r3d.view_perspective = "PERSP"
        r3d.update()
        area.tag_redraw()
        break
""")


def test_area_spaces_and_regions_may_be_traversed():
    validate_camera_view_code("""import bpy
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        for space in area.spaces:
            if space.type == "VIEW_3D":
                space.overlay.show_overlays = True
        for region in area.regions:
            if region.type == "WINDOW":
                area.tag_redraw()
                break
        break
""")


def test_all_allowed_context_roots_and_indexed_area_are_recognized():
    validate_camera_view_code("""import bpy
window = bpy.context.window
screen = window.screen
current_area = bpy.context.area
current_space = bpy.context.space_data
areas = screen.areas
area = areas[0]
regions = area.regions
spaces = area.spaces
space = spaces.active
r3d = space.region_3d
r3d.view_distance = 5.0
current_area.tag_redraw()
""")


def test_workspace_status_is_an_explicit_ui_only_operation():
    validate_camera_view_code("""import bpy
workspace = bpy.context.window.workspace
workspace.status_text_set("Inspecting viewport")
""")


@pytest.mark.parametrize(
    "code",
    [
        "import bpy\nbpy.ops.object.delete()\nbpy.context.scene.camera.data.lens = 50",
        "import bpy\nbpy.context.scene.render.resolution_x = 100",
        "import bpy\nbpy.data.objects['Cube'].location = (0, 0, 0)",
        "import os\nimport bpy\nbpy.context.scene.camera.data.lens = 50",
        "import bpy\nprint(bpy.data.filepath)\nbpy.context.scene.camera.data.lens = 50",
        "import bpy\nprint(bpy.context.scene.camera)",
        "",
    ],
)
def test_non_camera_code_is_rejected(code):
    with pytest.raises(ValueError):
        validate_camera_view_code(code)


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (
            "import bpy\nbpy.data.objects['Cube'].location = (0, 0, 0)",
            "outside the camera/viewport UI allowlist",
        ),
        (
            "import bpy\nbpy.data.meshes['Mesh'].vertices[0].co = (0, 0, 0)",
            "outside the camera/viewport UI allowlist",
        ),
        (
            "import bpy\nbpy.data.materials['Material'].diffuse_color = (1, 0, 0, 1)",
            "outside the camera/viewport UI allowlist",
        ),
        (
            "import bpy\nbpy.context.scene.objects['Cube'].scale = (2, 2, 2)",
            "outside the camera/viewport UI allowlist",
        ),
        ("open('/tmp/escape', 'w')", "call to 'open' is not allowed"),
        ("import subprocess\nsubprocess.run(['true'])", "only unaliased bpy"),
        ("import os\nos.system('true')", "only unaliased bpy"),
        ("import socket\nsocket.create_connection(('example.com', 80))", "only unaliased bpy"),
        ("import urllib.request\nurllib.request.urlopen('https://example.com')", "only unaliased bpy"),
        (
            "import bpy\nspace = bpy.context.space_data\nspace.unknown.setting = 1",
            "outside the camera/viewport UI allowlist",
        ),
        (
            "import bpy\narea = bpy.context.area\ngetattr(area, 'spaces')",
            "call to 'getattr' is not allowed",
        ),
        (
            "import bpy\narea = bpy.context.area\nx = area.__class__\narea.tag_redraw()",
            "private and special attributes are not allowed",
        ),
    ],
)
def test_scene_data_io_network_unknown_and_reflection_are_rejected(code, reason):
    with pytest.raises(ValueError, match=reason.replace("(", r"\(").replace(")", r"\)")):
        validate_camera_view_code(code)


@pytest.mark.parametrize(
    "code",
    [
        """import bpy
space = bpy.context.space_data
space.shading.type = "NOT_A_SHADING_MODE"
""",
        """import bpy
space = bpy.context.space_data
space.overlay.show_overlays = 1
""",
        """import bpy
r3d = bpy.context.space_data.region_3d
r3d.view_perspective = "INVALID"
""",
        """import bpy
bpy.context.area.tag_redraw(123)
""",
        """import bpy
r3d = bpy.context.space_data.region_3d
r3d.update(force=True)
""",
    ],
)
def test_viewport_values_and_calls_remain_narrowly_validated(code):
    with pytest.raises(ValueError):
        validate_camera_view_code(code)

# BlenderMCP — viewport-only variant

A deliberately restricted Blender MCP server. An agent connected to it can **look at a
scene from any viewpoint, and nothing else**: it cannot read, create, modify or delete
scene data, touch the filesystem or network, or reach arbitrary Python.

This branch is the agent interface behind the *Active Visual* setting of
**3DHarnessBench**, where the benchmark must grant free viewpoint control while withholding
every other form of access. If the agent could inspect the target geometry, that setting
would collapse into *Full 3D Interaction* and the comparison between harness levels would
stop meaning anything. The restriction is therefore part of the experimental design, not a
deployment hardening measure.

## What the server exposes

Exactly two MCP tools:

| Tool | Purpose |
| --- | --- |
| `get_viewport_screenshot(max_size=1000, user_prompt="")` | Renders the active `VIEW_3D` area through a GPU off-screen buffer, so it works headless under Xvfb. |
| `execute_blender_code(code, user_prompt="")` | Runs a statically validated Python subset, restricted to camera and viewport/UI state. |

Everything else from upstream — object and mesh creation, material and texture tools, asset
integrations, the asset-creation prompt, telemetry — has been removed. The Blender add-on is
reduced to a two-handler socket build on `DEFAULT_PORT 8888`.

## How the restriction works

The add-on executes whatever it receives with a plain `exec()`. The guard therefore lives
**entirely on the server side**: `validate_camera_view_code()` in
[`src/blender_mcp/validator.py`](src/blender_mcp/validator.py) parses the submitted code and
walks its AST, rejecting anything outside a small allowlist *before* the code is sent to
Blender.

The allowlist is expressed as an explicit, typed graph of the UI objects reachable from
`bpy.context`. An attribute missing from that graph is not treated as merely unknown, it is
outside the capability and is refused. Keeping the graph explicit stops any permitted UI
object from becoming a bridge to arbitrary RNA or Python attributes.

**Permitted:**

- active camera transform — `location`, `matrix_world`, `rotation_euler`, `rotation_mode`,
  `rotation_quaternion`
- camera data — `lens`, `clip_start`, `clip_end`, `ortho_scale`, `sensor_fit`,
  `sensor_width`, `sensor_height`, `shift_x`, `shift_y`, `type`
- viewport state on `region_3d` — `view_location`, `view_rotation`, `view_distance`,
  `view_matrix`, `view_camera_offset`, `view_camera_zoom`, `view_perspective`,
  `lock_rotation`
- shading (`WIREFRAME`, `SOLID`, `MATERIAL`, `RENDERED`), overlay toggle, workspace status
  text, `area.tag_redraw()` and `region_3d.update()`
- unaliased imports of `bpy`, `math` and `mathutils` only, the latter limited to camera
  transform types
- literal integer indexing of viewport UI collections (`areas`, `regions`, `spaces`)

**Refused**, each with the offending line reported back: scene, object, mesh and material
access; filesystem and network; dynamic reflection; private and dunder attributes;
comprehensions; lambdas; function and class definitions; loops; `try`, `raise`, `assert`;
`global`; assignment expressions; context managers; deletion; annotation-only assignment;
subscripting outside those UI collections; and any call outside the small permitted set.

The intended behaviour is pinned by 15 tests in
[`test_viewport_only.py`](test_viewport_only.py), which assert both directions: that the
legal camera and viewport operations pass, and that scene access, I/O, network, reflection
and unknown attributes are rejected. Treat that file as the contract.

## Building

This branch depends on the 3D-CoT superproject's `blender-mcp-core` as an editable path
dependency at `../core`, so it builds **inside a 3D-CoT checkout** — as the
`BlenderMCP/viewport_only` submodule, with `BlenderMCP/core` beside it — rather than
standalone.

## Attribution and licence

Derived from [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp), which has
since been removed from GitHub. The `main` branch of this repository preserves an unmodified
mirror of that upstream project; this branch is the restricted variant built on top of it.
MIT licensed, as upstream was.

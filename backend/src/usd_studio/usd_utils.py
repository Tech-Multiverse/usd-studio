"""USD scene composition helpers.

Builds an inline USDA layer that references an existing scene and injects a
Camera, DomeLight, and RenderProduct if the scene does not provide usable ones.
"""

from pathlib import Path


def _camera_path_exists(prims: list[str]) -> str | None:
    for p in prims:
        if p.endswith("/Camera") or p.endswith("/Camera0") or p.endswith("/MainCamera"):
            return p
    return None


def _render_product_exists(prims: list[str]) -> str | None:
    for p in prims:
        if "RenderProduct" in p:
            return p
    return None


def build_scene_layer(
    scene_path: Path,
    camera_path: str | None = None,
    render_product_path: str | None = None,
    width: int = 1280,
    height: int = 720,
    camera_transform: tuple | None = None,
) -> tuple[str, str, str]:
    """Return (layer_usda, camera_path, render_product_path) for the composed scene.

    The returned USDA string subLayers the original scene and adds missing render
    configuration. Paths are returned so the renderer knows what to step.
    """
    scene_path = scene_path.resolve()

    # Defaults
    camera_path = camera_path or "/Studio/Camera"
    render_product_path = render_product_path or "/Studio/RenderProduct"
    render_var_path = "/Studio/Vars/LdrColor"

    if camera_transform is None:
        camera_transform = {
            "translate": (0.3, -0.35, 0.2),
            "rotateYXZ": (-20.0, 50.0, 0.0),
        }

    tx, ty, tz = camera_transform["translate"]
    rx, ry, rz = camera_transform["rotateYXZ"]

    usda = f"""#usda 1.0
(
    defaultPrim = "Studio"
    subLayers = [
        @{_escape_asset_path(scene_path)}@
    ]
)

def "Studio"
{{
    def Camera "Camera" (
        prepend apiSchemas = ["OmniRtxCameraAutoExposureAPI_1", "OmniRtxCameraExposureAPI_1"]
    )
    {{
        float2 clippingRange = (0.001, 10000)
        float focalLength = 18.0
        float focusDistance = 5
        float fStop = 0
        float horizontalAperture = 20.955
        token projection = "perspective"
        token purpose = "default"
        float verticalAperture = 11.76
        token visibility = "inherited"
        float3 xformOp:rotateYXZ = ({rx}, {ry}, {rz})
        float3 xformOp:scale = (1, 1, 1)
        double3 xformOp:translate = ({tx}, {ty}, {tz})
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateYXZ", "xformOp:scale"]
    }}

    def DomeLight "DomeLight" (
        prepend apiSchemas = ["ShapingAPI"]
    )
    {{
        float inputs:intensity = 1000
        token inputs:texture:format = "latlong"
        color3f color = (1, 1, 1)
        float intensity = 1000
        double3 xformOp:rotateXYZ = (270, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
    }}

    def DistantLight "DistantLight" (
        prepend apiSchemas = ["ShapingAPI"]
    )
    {{
        float angle = 0.53
        color3f color = (1, 1, 1)
        float intensity = 3000
        float3 xformOp:rotateXYZ = (315, 45, 0)
        uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
    }}

    def RenderProduct "RenderProduct" (
        prepend apiSchemas = ["OmniRtxSettingsCommonAdvancedAPI_1", "OmniRtxSettingsRtAdvancedAPI_1", "OmniRtxSettingsPtAdvancedAPI_1"]
    )
    {{
        rel camera = </Studio/Camera>
        token omni:rtx:background:source:type = "domeLight"
        color3f omni:rtx:rt:ambientLight:color = (0.1, 0.1, 0.1)
        rel orderedVars = </Studio/Vars/LdrColor>
        uniform int2 resolution = ({width}, {height})
    }}

    def "Vars"
    {{
        def RenderVar "LdrColor"
        {{
            uniform string sourceName = "LdrColor"
        }}
    }}
}}
"""
    return usda, camera_path, render_product_path


def _escape_asset_path(path: Path) -> str:
    # On Windows, USD asset paths need forward slashes; spaces must be URL-style
    # escaped for the @...@ syntax. Keep it simple: replace backslashes and spaces.
    return str(path.as_posix()).replace(" ", "%20")

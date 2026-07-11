import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "data" / "nut-and-bolt" / "official_hex_sim.usda"
DST = ROOT / "data" / "nut-and-bolt" / "studio_scene.usda"

src_text = SRC.read_text()

# Replace absolute references to the shipped hex_bolt assets.
src_text = src_text.replace(
    '@D:/omniverse/threading_sim/HexAssembly/bolt.usd@',
    '@./hex_bolt/bolt.usd@',
)
src_text = src_text.replace(
    '@D:/omniverse/threading_sim/HexAssembly/nut.usd@',
    '@./hex_bolt/nut.usd@',
)

# Remove the missing metrics sublayer reference so composition doesn't fail.
src_text = re.sub(
    r'\n\s+@metrics:UnitsAdjust-[^@]+\.metricsAssembler@,?',
    '',
    src_text,
)

DST.write_text(src_text)
print(f"Created {DST}")

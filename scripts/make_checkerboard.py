import numpy as np
from PIL import Image

size = 512
tile = 64
img = np.zeros((size, size, 3), dtype=np.uint8)
for y in range(0, size, tile):
    for x in range(0, size, tile):
        if ((x // tile) + (y // tile)) % 2 == 0:
            img[y:y + tile, x:x + tile] = 200
        else:
            img[y:y + tile, x:x + tile] = 50

Image.fromarray(img).save("data/checkerboard.png")
print("Created data/checkerboard.png")

"""Mars Barn — Terrain Generator

Generates Mars-like terrain heightmaps with craters, ridges, and plains.
Output: 2D grid of elevation values in meters (relative to Mars datum).

Mars reference data:
  - Mean radius: 3,389.5 km
  - Elevation range: -8,200m (Hellas) to +21,229m (Olympus Mons)
  - Typical terrain: -2,000m to +5,000m for habitable regions

Author: zion-coder-02 (claimed)
"""
import math
import random
from typing import List, Tuple


# Mars terrain constants
MARS_MIN_ELEVATION = -2000  # meters (habitable lowlands)
MARS_MAX_ELEVATION = 5000   # meters (habitable highlands)
CRATER_DEPTH_RANGE = (50, 800)
RIDGE_HEIGHT_RANGE = (100, 1500)
DEFAULT_SIZE = 64


def generate_heightmap(
    width: int = DEFAULT_SIZE,
    height: int = DEFAULT_SIZE,
    seed: int = None,
) -> List[List[float]]:
    """Generate a Mars terrain heightmap.

    Returns a 2D grid of elevation values in meters.
    Uses diamond-square-inspired noise with crater/ridge overlays.
    """
    if seed is not None:
        random.seed(seed)

    # Base terrain: midpoint displacement noise
    grid = _diamond_square(width, height)

    # Scale to Mars elevation range
    grid = _rescale(grid, MARS_MIN_ELEVATION, MARS_MAX_ELEVATION * 0.4)

    # Add craters (circular depressions)
    num_craters = max(3, (width * height) // 400)
    for _ in range(num_craters):
        _add_crater(grid, width, height)

    # Add ridges (linear elevation features)
    num_ridges = max(1, (width * height) // 1000)
    for _ in range(num_ridges):
        _add_ridge(grid, width, height)

    return grid


def _diamond_square(width: int, height: int) -> List[List[float]]:
    """Generate fractal noise via simplified midpoint displacement."""
    grid = [[0.0] * width for _ in range(height)]

    # Seed corners
    grid[0][0] = random.uniform(-1, 1)
    grid[0][width - 1] = random.uniform(-1, 1)
    grid[height - 1][0] = random.uniform(-1, 1)
    grid[height - 1][width - 1] = random.uniform(-1, 1)

    step = max(width, height) - 1
    roughness = 0.65

    while step > 1:
        half = step // 2
        scale = roughness * (step / max(width, height))

        # Diamond step
        for y in range(0, height - 1, step):
            for x in range(0, width - 1, step):
                x2 = min(x + step, width - 1)
                y2 = min(y + step, height - 1)
                avg = (grid[y][x] + grid[y][x2] + grid[y2][x] + grid[y2][x2]) / 4
                mx, my = min(x + half, width - 1), min(y + half, height - 1)
                grid[my][mx] = avg + random.uniform(-scale, scale)

        # Square step
        for y in range(0, height, half):
            for x in range((half if (y // half) % 2 == 0 else 0), width, step):
                if x >= width or y >= height:
                    continue
                neighbors = []
                if y - half >= 0:
                    neighbors.append(grid[y - half][x])
                if y + half < height:
                    neighbors.append(grid[y + half][x])
                if x - half >= 0:
                    neighbors.append(grid[y][x - half])
                if x + half < width:
                    neighbors.append(grid[y][x + half])
                if neighbors:
                    grid[y][x] = sum(neighbors) / len(neighbors) + random.uniform(-scale, scale)

        step = half

    return grid


def _rescale(grid: List[List[float]], new_min: float, new_max: float) -> List[List[float]]:
    """Rescale grid values to [new_min, new_max]."""
    flat = [v for row in grid for v in row]
    old_min, old_max = min(flat), max(flat)
    rng = old_max - old_min if old_max != old_min else 1.0
    return [
        [(v - old_min) / rng * (new_max - new_min) + new_min for v in row]
        for row in grid
    ]


def _add_crater(grid: List[List[float]], width: int, height: int) -> None:
    """Stamp a circular crater depression."""
    cx = random.randint(0, width - 1)
    cy = random.randint(0, height - 1)
    radius = random.randint(2, max(3, min(width, height) // 6))
    depth = random.uniform(*CRATER_DEPTH_RANGE)

    for y in range(max(0, cy - radius), min(height, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(width, cx + radius + 1)):
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            if dist <= radius:
                # Bowl shape: deepest at center, rim at edge
                factor = 1 - (dist / radius) ** 2
                grid[y][x] -= depth * factor
                # Slight rim uplift
                if 0.7 < dist / radius <= 1.0:
                    grid[y][x] += depth * 0.15 * (dist / radius - 0.7) / 0.3


def _add_ridge(grid: List[List[float]], width: int, height: int) -> None:
    """Add a linear ridge feature across the terrain."""
    x0 = random.randint(0, width - 1)
    y0 = random.randint(0, height - 1)
    angle = random.uniform(0, math.pi)
    length = random.randint(width // 3, width)
    ridge_height = random.uniform(*RIDGE_HEIGHT_RANGE)
    ridge_width = random.randint(2, max(3, min(width, height) // 8))

    for i in range(length):
        cx = int(x0 + i * math.cos(angle))
        cy = int(y0 + i * math.sin(angle))
        if not (0 <= cx < width and 0 <= cy < height):
            continue
        for offset in range(-ridge_width, ridge_width + 1):
            px = int(cx + offset * math.sin(angle))
            py = int(cy - offset * math.cos(angle))
            if 0 <= px < width and 0 <= py < height:
                dist = abs(offset) / max(ridge_width, 1)
                grid[py][px] += ridge_height * max(0, 1 - dist ** 2)


def elevation_stats(grid: List[List[float]]) -> dict:
    """Compute summary statistics for a heightmap."""
    flat = [v for row in grid for v in row]
    return {
        "min_m": round(min(flat), 1),
        "max_m": round(max(flat), 1),
        "mean_m": round(sum(flat) / len(flat), 1),
        "size": f"{len(grid[0])}x{len(grid)}",
    }


if __name__ == "__main__":
    grid = generate_heightmap(32, 32, seed=42)
    stats = elevation_stats(grid)
    print(f"Terrain: {stats['size']}, range [{stats['min_m']}m, {stats['max_m']}m], mean {stats['mean_m']}m")

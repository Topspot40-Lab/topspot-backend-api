import json
from pathlib import Path


FILES = [
    Path("data/softrock/yacht_rock.json"),
    Path("data/softrock/singer_songwriter.json"),
]


def flatten_tracks(data: dict) -> dict:
    for collection in data["collections"]:
        fixed_tracks = []

        for item in collection["tracks"]:
            if "collections" in item:
                nested_collection = item["collections"][0]
                fixed_tracks.extend(nested_collection["tracks"])
            else:
                fixed_tracks.append(item)

        collection["tracks"] = sorted(fixed_tracks, key=lambda t: t["rank"])

    return data


def main() -> None:
    for path in FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        fixed = flatten_tracks(data)

        backup_path = path.with_suffix(".backup.json")
        backup_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        path.write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding="utf-8")

        count = len(fixed["collections"][0]["tracks"])
        print(f"Fixed {path} — {count} tracks")


if __name__ == "__main__":
    main()
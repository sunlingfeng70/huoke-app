from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .models import UserRecord
from .parser import scan_vault
from .generators import (
    CONTACT_DIR,
    OUTPUT_DIR,
    build_index_generators,
    write_contact_notes,
    _aggregate_contacts,
)


def run_organizer(
    vault_path: str | Path,
    output_dir: str = OUTPUT_DIR,
    contact_dir: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    root = Path(vault_path).resolve()
    if not root.exists():
        print(f"❌ 路径不存在: {root}")
        return {"status": "error", "message": f"路径不存在: {root}"}

    output_path = root / output_dir
    output_path.mkdir(parents=True, exist_ok=True)

    print("🔍 扫描评论库...")
    users = scan_vault(root, verbose=verbose)
    print(f"   共发现 {len(users)} 条用户评论记录")

    if not users:
        print("⚠️  未找到评论数据，跳过索引生成")
        return {"status": "empty", "total_users": 0}

    print("\n📊 生成索引页面...")
    for name, content in build_index_generators(users):
        fp = output_path / name
        fp.write_text(content, encoding="utf-8")
        print(f"  ✅ 生成: {output_dir}/{name}")

    print("\n📇 聚合联系人...")
    contacts = _aggregate_contacts(users)
    print(f"   共识别 {len(contacts)} 位独立联系人")

    contact_path = root / (contact_dir or OUTPUT_DIR.rsplit("/", 1)[0])
    contact_path.mkdir(parents=True, exist_ok=True)

    print("\n📝 生成联系人笔记...")
    written = write_contact_notes(contacts, root, verbose=verbose)
    print(f"   已生成 {len(written)} 个文件")

    level_counts = {
        lv: len([c for c in contacts if c.level == lv])
        for lv in ("A", "B", "C", "D")
    }

    summary = {
        "status": "success",
        "total_users": len(users),
        "total_contacts": len(contacts),
        "level_counts": level_counts,
        "generated_files": len(written),
    }
    print("\n" + "=" * 40)
    print("📋 联系人等级分布:")
    for lv, count in level_counts.items():
        label = {"A": "高意向", "B": "中意向", "C": "低意向", "D": "暂不跟进"}[lv]
        if count:
            avg = sum(c.score for c in contacts if c.level == lv) / count
            print(f"   {lv}类 ({label}): {count} 人, 均分 {avg:.0f}")
        else:
            print(f"   {lv}类 ({label}): {count} 人")

    print(f"\n✅ 完成! 索引位于: {output_dir}/")
    print(f"   联系人位于: {CONTACT_DIR}/")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="小红书 Obsidian 获客组织器")
    parser.add_argument("vault_path", type=str, help="Obsidian 仓库根目录路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细扫描信息")
    args = parser.parse_args()
    run_organizer(args.vault_path, verbose=args.verbose)


if __name__ == "__main__":
    main()

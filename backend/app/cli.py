"""运维 CLI：python -m app.cli wizard:unlock | secret:rotate | doctor

wizard:unlock  应急解锁（本机执行即视为授权，无需密码），config.json 与 DB 审计双写。
secret:rotate  轮换主密钥并重加密所有 *_enc（需 DB 可用）。
doctor         体检：配置/密钥来源/DB 连通/表清单/迁移版本/静态产物。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from app.core.config_store import get_config_store
from app.core.security import new_id
from app.services import install_service

_COMMANDS = ("wizard:unlock", "secret:rotate", "doctor")


def _write_unlock_audit(action: str) -> bool:
    """尽力把审计写入 DB；DB 不可用时返回 False（不阻断应急解锁）。"""
    try:
        from app.db.session import get_session
        from app.models.config import AppConfig

        SessionLocal = get_session()
        db = SessionLocal()
        try:
            db.add(
                AppConfig(
                    key=f"audit:{action}:{new_id()}",
                    value_plain=json.dumps(
                        {"action": action, "at": datetime.now(timezone.utc).isoformat(), "via": "cli"},
                        ensure_ascii=False,
                    ),
                )
            )
            db.commit()
        finally:
            db.close()
        return True
    except Exception:  # noqa: BLE001
        return False


def cmd_wizard_unlock() -> int:
    store = get_config_store()
    cfg = store.load()
    cfg["unlocked_at"] = datetime.now(timezone.utc).isoformat()
    store.save(cfg)
    audited = _write_unlock_audit("cli:wizard:unlock")
    print("已应急解锁（无需密码）。")
    if not audited:
        print("警告：DB 不可用，审计记录未写入，请稍后核查。")
    return 0


def cmd_secret_rotate() -> int:
    try:
        from app.db.session import get_session

        SessionLocal = get_session()
    except Exception as exc:  # noqa: BLE001
        print(f"数据库不可用，无法轮换密钥：{type(exc).__name__}")
        return 1
    db = SessionLocal()
    try:
        result = install_service.rotate_secret(db)
    except Exception as exc:  # noqa: BLE001
        print(f"密钥轮换失败：{exc}")
        return 1
    finally:
        db.close()
    print("主密钥已轮换，所有 *_enc 已重加密。")
    print(f"请立即备份新主密钥并更新 FLASHTRIP_SECRET_KEY：{result['secret_key']}")
    return 0


def cmd_doctor() -> int:
    print(json.dumps(install_service.doctor(), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="FlashTrip 运维命令")
    parser.add_argument("command", choices=_COMMANDS, help="要执行的命令")
    args = parser.parse_args(argv)
    handlers = {
        "wizard:unlock": cmd_wizard_unlock,
        "secret:rotate": cmd_secret_rotate,
        "doctor": cmd_doctor,
    }
    return handlers[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())

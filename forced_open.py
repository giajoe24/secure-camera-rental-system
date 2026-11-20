# 追加機能: 不正な開放の検知(config.USE_FORCED_OPEN_CHECK)
# プログラムが解錠していないのに、マイクロスイッチが「開いた」になったら
# (こじ開けられた、ロックが壊れた など)記録して、警告の画面を出す。
# 扉が閉まったらホームに戻る。部品は今のマイクロスイッチだけで足りる。

import logging

import events
from gui_parts import RED_TAG, SUB_TEXT_COLOR, Screen, make_label, make_tag

log = logging.getLogger(__name__)


def check(app):
    # gui.py の every_second から 1 秒ごとに呼ばれる
    if app.screen.door_may_be_open:   # 解錠して扉を待っている画面などでは調べない
        return
    if app.lock.is_locked() is False:
        log.warning("解錠していないのに扉が開きました")
        events.add_event(app.database, events.FORCED_OPEN, "解錠していないのに扉が開いた")
        app.show(ForcedOpenScreen)


class ForcedOpenScreen(Screen):
    idle_timeout = False
    door_may_be_open = True   # この画面にいる間は、もう一度は調べない

    def __init__(self, app):
        super().__init__(app)
        self.footer.pack_forget()
        make_tag(self.top_area, "  警告  ", RED_TAG).pack(anchor="w", pady=(0, 10))
        make_label(self.top_area, "扉が開いています", 28, True, RED_TAG[0]).pack(anchor="w")
        make_label(self.top_area, "ロックを外していないのに扉が開きました。管理者に連絡してください。", 20,
                   True).pack(anchor="w", pady=(8, 0))
        make_label(self.content_area, "扉を閉めると、ホームに戻ります。", color=SUB_TEXT_COLOR).pack(anchor="w")
        self.wait_for_close()

    def wait_for_close(self):
        if self.app.lock.is_locked():
            log.info("扉が閉まりました")
            self.app.go_home()
            return
        self.run_later(500, self.wait_for_close)

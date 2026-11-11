"""
このシステムで使う例外(エラー)の定義

【設計メモ】
    画面に Python の例外文をそのまま出さないために、
    各例外に「利用者向けの日本語メッセージ」を持たせています。

    ・title       : 画面に大きく表示する見出し
    ・user_message: 何が起きたか + 次に何をすればよいか

    詳しい原因(元の例外)はログファイルへ記録します。
"""


class CameraRentalError(Exception):
    """このシステムで発生するエラーの共通の親クラス"""

    title = "エラーが発生しました"
    user_message = "もう一度お試しください。解決しない場合は管理者に連絡してください。"

    def __init__(self, user_message=None, title=None, detail=None):
        # 呼び出し側でメッセージを上書きしたい場合だけ指定する
        if user_message is not None:
            self.user_message = user_message
        if title is not None:
            self.title = title

        # detail はログ用の詳細情報(画面には出さない)
        self.detail = detail

        super().__init__(detail or self.user_message)


# --------------------------------------------------
# 利用者・認証関連
# --------------------------------------------------

class UnknownCardError(CameraRentalError):
    """登録されていない社員証がかざされた"""

    title = "登録されていない社員証です"
    user_message = "利用登録は管理者に依頼してください。"


class UserDisabledError(CameraRentalError):
    """利用停止中の利用者"""

    title = "この社員証は利用停止中です"
    user_message = "詳しくは管理者に確認してください。"


class DuplicateUserError(CameraRentalError):
    """社員番号またはカードIDが既に登録されている"""

    title = "利用者を登録できません"
    user_message = "同じ社員番号またはカードIDの利用者が、すでに登録されています。"


class UserNotFoundError(CameraRentalError):
    """指定した利用者が見つからない(管理用)"""

    title = "利用者が見つかりません"
    user_message = "指定した利用者は登録されていません。"


# --------------------------------------------------
# カメラ・貸出関連
# --------------------------------------------------

class DuplicateCameraError(CameraRentalError):
    """同じ名前のカメラが既に登録されている"""

    title = "カメラを登録できません"
    user_message = "同じ名前のカメラが、すでに登録されています。"


class CameraNotFoundError(CameraRentalError):
    """指定したカメラが見つからない"""

    title = "カメラが見つかりません"
    user_message = "選択したカメラが見つかりませんでした。最初からやり直してください。"


class NoAvailableCameraError(CameraRentalError):
    """貸出できるカメラが1台もない"""

    title = "貸し出せるカメラがありません"
    user_message = "ホーム画面で返却予定を確認してください。"


class CameraNotAvailableError(CameraRentalError):
    """選んだカメラが貸出中・点検中になっていた"""

    title = "このカメラは貸し出せません"
    user_message = "別のカメラを選んでください。"


class UserHasActiveRentalError(CameraRentalError):
    """利用者が未返却のカメラを持っている"""

    title = "返却していないカメラがあります"
    user_message = "先にカメラを返却してください。"


class NoActiveRentalError(CameraRentalError):
    """返却しようとしたが、貸出中のカメラがない"""

    title = "返却するカメラがありません"
    user_message = "借りた本人の社員証でかざしてください。"


class RentalNotFoundError(CameraRentalError):
    """指定した貸出記録が見つからない"""

    title = "貸出記録が見つかりません"
    user_message = "対象の貸出記録が見つかりませんでした。管理者に連絡してください。"


class InvalidRentalHoursError(CameraRentalError):
    """設定にない貸出時間が指定された"""

    title = "貸出時間が正しくありません"
    user_message = "貸出時間を選び直してください。"


# --------------------------------------------------
# データベース・ファイル関連
# --------------------------------------------------

class DatabaseError(CameraRentalError):
    """SQLite への読み書きに失敗した"""

    title = "記録できませんでした"
    user_message = "扉は開けていません。もう一度お試しください。"


class CsvExportError(CameraRentalError):
    """CSV ファイルの保存に失敗した"""

    title = "CSVを保存できませんでした"
    user_message = "保存先のフォルダと空き容量を確認してください。"


# --------------------------------------------------
# ハードウェア関連
# --------------------------------------------------

class CardReaderNotConnectedError(CameraRentalError):
    """カードリーダーが見つからない・開けない"""

    title = "カードリーダーが使えません"
    user_message = "管理者に連絡してください。"


class CardReadError(CameraRentalError):
    """社員証の読み取りに失敗した"""

    title = "社員証を読み取れませんでした"
    user_message = "カードリーダーの中央に置いて、動かさずにお待ちください。"


class LockInitError(CameraRentalError):
    """電磁ロック(GPIO)の初期化に失敗した"""

    title = "扉のロックが使えません"
    user_message = "貸出・返却を停止しています。管理者に連絡してください。"


class UnlockError(CameraRentalError):
    """解錠に失敗した"""

    title = "扉を開けられませんでした"
    user_message = "もう一度お試しください。"

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
    user_message = (
        "この社員証は貸出システムに登録されていません。\n"
        "利用登録が必要な場合は、管理者に連絡してください。"
    )


class UserDisabledError(CameraRentalError):
    """利用停止中の利用者"""

    title = "現在この社員証は利用できません"
    user_message = (
        "この利用者は利用停止に設定されています。\n"
        "詳しくは管理者に確認してください。"
    )


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

    title = "貸出できるカメラがありません"
    user_message = (
        "現在、すべてのカメラが貸出中または点検中です。\n"
        "「貸出状況」画面で返却予定日時を確認してください。"
    )


class CameraNotAvailableError(CameraRentalError):
    """選んだカメラが貸出中・点検中になっていた"""

    title = "このカメラは貸出できません"
    user_message = (
        "選択したカメラは、ほかの方が貸出中か点検中です。\n"
        "お手数ですが、別のカメラを選んでください。"
    )


class UserHasActiveRentalError(CameraRentalError):
    """利用者が未返却のカメラを持っている"""

    title = "返却されていないカメラがあります"
    user_message = (
        "前回貸出したカメラが、まだ返却されていません。\n"
        "先にカメラを返却してから、もう一度貸出してください。"
    )


class NoActiveRentalError(CameraRentalError):
    """返却しようとしたが、貸出中のカメラがない"""

    title = "返却するカメラがありません"
    user_message = (
        "この社員証で貸出中のカメラはありません。\n"
        "別の方の社員証で貸出した場合は、その方の社員証で返却してください。"
    )


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

    title = "データを保存できませんでした"
    user_message = (
        "記録の保存に失敗したため、処理を中止しました。\n"
        "ロックは解錠していません。もう一度お試しください。\n"
        "繰り返し発生する場合は管理者に連絡してください。"
    )


class CsvExportError(CameraRentalError):
    """CSV ファイルの保存に失敗した"""

    title = "CSVファイルを保存できませんでした"
    user_message = (
        "保存先のフォルダに書き込めませんでした。\n"
        "ファイルを開いたままにしていないか、空き容量があるか確認してください。"
    )


# --------------------------------------------------
# ハードウェア関連
# --------------------------------------------------

class CardReaderNotConnectedError(CameraRentalError):
    """カードリーダーが見つからない・開けない"""

    title = "カードリーダーが見つかりません"
    user_message = (
        "カードリーダーが接続されていないか、使用できない状態です。\n"
        "管理者に連絡してください。"
    )


class CardReadError(CameraRentalError):
    """社員証の読み取りに失敗した"""

    title = "社員証を読み取れませんでした"
    user_message = (
        "社員証をカードリーダーの中央に、動かさずにかざしてください。\n"
        "もう一度お試しください。"
    )


class LockInitError(CameraRentalError):
    """電磁ロック(GPIO)の初期化に失敗した"""

    title = "電磁ロックが使用できません"
    user_message = (
        "電磁ロックの制御装置を準備できませんでした。\n"
        "貸出・返却は停止しています。管理者に連絡してください。"
    )


class UnlockError(CameraRentalError):
    """解錠に失敗した"""

    title = "ロックを解錠できませんでした"
    user_message = "もう一度解錠をお試しください。解決しない場合は管理者に連絡してください。"

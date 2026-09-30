"""Safe errors raised before any outbound model request is constructed."""


class ModelConnectionUnavailable(RuntimeError):
    """Account connection state could not be read or decrypted reliably."""

    def __init__(self):
        super().__init__(
            "无法安全读取当前模型连接配置，已停止本次请求，未自动切换厂商或密钥。"
            "请检查模型配置，或在配置服务恢复后重试。"
        )

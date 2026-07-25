from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "USD Studio"
    host: str = "127.0.0.1"
    port: int = 8000
    webrtc_signal_port: int = 49101
    render_width: int = 1280
    render_height: int = 720
    target_fps: float = 60.0
    data_dir: str = "./data"
    outputs_dir: str = "../outputs"
    uploads_dir: str = "./uploads"
    max_package_files: int = 20000
    max_package_upload_bytes: int = 2 * 1024 * 1024 * 1024
    max_package_expanded_bytes: int = 5 * 1024 * 1024 * 1024
    default_scene: str = ""

    class Config:
        env_file = ".env"


settings = Settings()

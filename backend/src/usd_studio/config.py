from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "USD Studio"
    host: str = "127.0.0.1"
    port: int = 8000
    webrtc_signal_port: int = 49100
    render_width: int = 1280
    render_height: int = 720
    target_fps: float = 60.0
    data_dir: str = "./data"
    outputs_dir: str = "../outputs"
    uploads_dir: str = "./uploads"
    default_scene: str = ""

    class Config:
        env_file = ".env"


settings = Settings()

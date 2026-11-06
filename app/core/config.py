import os
from dotenv import load_dotenv

load_dotenv()

def normalize_database_url(url: str | None = None) -> str:
    """Ensure database URL uses driver compatible with SQLAlchemy 2.0, supporting Railway MySQL/Postgres & local."""
    if not url:
        url = (
            os.getenv("DATABASE_URL")
            or os.getenv("DATABASE_PRIVATE_URL")
            or os.getenv("MYSQL_URL")
            or os.getenv("MYSQL_PRIVATE_URL")
            or os.getenv("POSTGRES_URL")
            or os.getenv("POSTGRES_PRIVATE_URL")
            or os.getenv("DATABASE_PUBLIC_URL")
            or ""
        )
    url = (url or "").strip().strip('"').strip("'")
    if not url:
        # Automatically detect Railway MySQL plugin environment variables
        m_host = os.getenv("MYSQLHOST")
        if m_host:
            m_port = os.getenv("MYSQLPORT", "3306")
            m_user = os.getenv("MYSQLUSER", "root")
            m_pass = os.getenv("MYSQLPASSWORD", "")
            m_db = os.getenv("MYSQLDATABASE", "railway")
            url = f"mysql+pymysql://{m_user}:{m_pass}@{m_host}:{m_port}/{m_db}"
        elif os.getenv("PGHOST") or os.getenv("POSTGRESHOST"):
            p_host = os.getenv("PGHOST") or os.getenv("POSTGRESHOST")
            p_port = os.getenv("PGPORT") or os.getenv("POSTGRESPORT") or "5432"
            p_user = os.getenv("PGUSER") or os.getenv("POSTGRESUSER") or os.getenv("POSTGRES_USER") or "postgres"
            p_pass = os.getenv("PGPASSWORD") or os.getenv("POSTGRESPASSWORD") or os.getenv("POSTGRES_PASSWORD") or ""
            p_db = os.getenv("PGDATABASE") or os.getenv("POSTGRESDATABASE") or os.getenv("POSTGRES_DB") or "railway"
            url = f"postgresql+psycopg2://{p_user}:{p_pass}@{p_host}:{p_port}/{p_db}"
        else:
            is_cloud = bool(
                os.getenv("RAILWAY_ENVIRONMENT")
                or os.getenv("RAILWAY_PROJECT_ID")
                or os.getenv("RAILWAY_SERVICE_ID")
                or os.getenv("RAILWAY_STATIC_URL")
                or os.getenv("RAILWAY_PUBLIC_DOMAIN")
                or os.getenv("DYNO")
                or os.getenv("RENDER")
            )
            if is_cloud:
                url = "sqlite:///./railway_data.db"
            else:
                url = "mysql+pymysql://root:root@localhost:3306/hotel_reservation"

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif url.startswith("mysql://") and not url.startswith("mysql+"):
        url = url.replace("mysql://", "mysql+pymysql://", 1)
    elif url.startswith("mysql2://"):
        url = url.replace("mysql2://", "mysql+pymysql://", 1)
    return url

def parse_cors_origins(raw: str | None) -> list[str]:
    """Parse comma-separated CORS origins, omitting '*' since allow_credentials=True is enabled."""
    if not raw:
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    origins = [x.strip() for x in raw.split(",") if x.strip() and x.strip() != "*"]
    return origins if origins else ["http://localhost:5173", "http://127.0.0.1:5173"]

class Settings:
    APP_NAME = os.getenv("APP_NAME", "StayFlow Hotel API")
    DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL"))
    PORT = int(os.getenv("PORT", "8000"))

    # Secure fallback JWT secret for cloud deployment if not set in Railway environment
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("APP_SECRET_KEY") or "stayflow_super_secret_jwt_key_2026_hotel_operations_railway_deploy"
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "43200"))
    CORS_ORIGINS = parse_cors_origins(os.getenv("CORS_ORIGINS"))
    APP_ENV = os.getenv("APP_ENV", "production")
    AUTO_MIGRATE = os.getenv("AUTO_MIGRATE", "true").lower() in ("true", "1", "yes")
    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET") or os.getenv("OUTGOING_WEBHOOK_SECRET") or ""
    ALLOW_INTERNAL_WEBHOOK_URLS = os.getenv("ALLOW_INTERNAL_WEBHOOK_URLS", "false").lower() in ("true", "1", "yes")

    # Configured Production Frontend Domain / URL for QR Codes & Public Guest Portals
    _raw_frontend = (
        os.getenv("FRONTEND_URL")
        or os.getenv("VITE_FRONTEND_URL")
        or os.getenv("PUBLIC_FRONTEND_URL")
        or os.getenv("VERCEL_PROJECT_PRODUCTION_URL")
        or os.getenv("VERCEL_URL")
        or ""
    ).strip().rstrip("/")
    FRONTEND_URL = f"https://{_raw_frontend}" if (_raw_frontend and not _raw_frontend.startswith("http://") and not _raw_frontend.startswith("https://")) else _raw_frontend

    # Agoda API
    AGODA_BASE_URL = os.getenv("AGODA_BASE_URL", "")
    AGODA_API_KEY = os.getenv("AGODA_API_KEY", "")
    AGODA_CLIENT_ID = os.getenv("AGODA_CLIENT_ID", "")
    AGODA_CLIENT_SECRET = os.getenv("AGODA_CLIENT_SECRET", "")

    # Booking.com Demand API
    BOOKING_COM_BASE_URL = os.getenv("BOOKING_COM_BASE_URL", "")
    BOOKING_COM_AFFILIATE_ID = os.getenv("BOOKING_COM_AFFILIATE_ID", "")
    BOOKING_COM_API_TOKEN = os.getenv("BOOKING_COM_API_TOKEN", "")

    # MakeMyTrip API
    MAKEMYTRIP_BASE_URL = os.getenv("MAKEMYTRIP_BASE_URL", "")
    MAKEMYTRIP_API_KEY = os.getenv("MAKEMYTRIP_API_KEY", "")
    MAKEMYTRIP_CLIENT_ID = os.getenv("MAKEMYTRIP_CLIENT_ID", "")
    # Google Gemini LLM
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    # Razorpay Payment Gateway (Strictly TEST MODE)
    RAZORPAY_KEY_ID = (os.getenv("RAZORPAY_KEY_ID") or "rzp_test_stayflow2026mock").strip()
    RAZORPAY_KEY_SECRET = (os.getenv("RAZORPAY_KEY_SECRET") or "stayflow_rzp_test_secret_mock_2026").strip()
    RAZORPAY_WEBHOOK_SECRET = (os.getenv("RAZORPAY_WEBHOOK_SECRET") or "stayflow_rzp_whsec_mock_2026").strip()
    RAZORPAY_MODE = (os.getenv("RAZORPAY_MODE") or "test").strip().lower()

    @classmethod
    def validate_razorpay_mode(cls):
        """Strictly enforce Razorpay TEST MODE. Prohibits live credentials."""
        mode = (os.getenv("RAZORPAY_MODE") or "test").strip().lower()
        key_id = (os.getenv("RAZORPAY_KEY_ID") or "").strip()
        if mode != "test":
            raise ValueError(f"StayFlow is strictly configured for Razorpay TEST MODE. Found RAZORPAY_MODE='{mode}'.")
        if key_id.startswith("rzp_live_"):
            raise ValueError("Live Razorpay credentials detected (rzp_live_*). Live transactions are prohibited; please use test credentials (rzp_test_*).")

settings = Settings()
settings.validate_razorpay_mode()

VERSION = "0005_rate_windows"


def upgrade(database) -> None:
    database.auth_rate_windows.create_index("expires_at", expireAfterSeconds=0)

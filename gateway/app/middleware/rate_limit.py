from app import limiter


# Rate limit decorators for specific endpoint groups
auth_limit = limiter.limit("20 per minute")
read_limit = limiter.limit("200 per minute")
write_limit = limiter.limit("60 per minute")
export_limit = limiter.limit("10 per minute")

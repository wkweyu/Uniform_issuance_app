import time
import functools
import logging
from flask import current_app

logger = logging.getLogger(__name__)

def time_execution(f):
    """Decorator to measure and log the execution time of a function."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        result = f(*args, **kwargs)
        end_time = time.time()
        duration = end_time - start_time
        logger.info(f"Function {f.__name__} executed in {duration:.4f} seconds")
        return result
    return decorated_function

def handle_errors(f):
    """Decorator to catch exceptions and log them."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {f.__name__}: {str(e)}", exc_info=True)
            raise e
    return decorated_function

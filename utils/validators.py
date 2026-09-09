import re

class Validators:
    @staticmethod
    def validate_email(email):
        pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        return bool(re.match(pattern, email))

    @staticmethod
    def validate_password(password):
        # Minimum 8 characters, at least one number and one letter
        return len(password) >= 8 and any(char.isdigit() for char in password) and any(char.isalpha() for char in password)
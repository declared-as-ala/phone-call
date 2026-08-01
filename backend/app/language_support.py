"""Language detection from phone country codes and multilingual speech templates."""

from __future__ import annotations

from typing import Literal, Optional

# Country code to language mapping (ISO 3166-1 alpha-2 to ISO 639-1)
COUNTRY_CODE_TO_LANGUAGE: dict[str, str] = {
    # Europe
    "ES": "es",  # Spain
    "FR": "fr",  # France
    "DE": "de",  # Germany
    "IT": "it",  # Italy
    "PT": "pt",  # Portugal
    "PL": "pl",  # Poland
    "NL": "nl",  # Netherlands
    "GB": "en",  # United Kingdom
    "IE": "en",  # Ireland
    "CH": "en",  # Switzerland (English fallback, or check region)
    "AT": "de",  # Austria
    "BE": "nl",  # Belgium (Dutch/Flemish)
    "CZ": "en",  # Czech Republic (English fallback)
    "GR": "en",  # Greece (English fallback)
    "HU": "en",  # Hungary (English fallback)
    "RO": "en",  # Romania (English fallback)
    "SE": "en",  # Sweden (English fallback)
    # Americas
    "US": "en",  # United States
    "CA": "en",  # Canada
    "MX": "es",  # Mexico
    "BR": "pt",  # Brazil
    "AR": "es",  # Argentina
    "CL": "es",  # Chile
    "CO": "es",  # Colombia
    "PE": "es",  # Peru
    # Asia
    "JP": "ja",  # Japan
    "CN": "zh",  # China (Mainland)
    "TW": "zh",  # Taiwan
    "SG": "en",  # Singapore
    "IN": "en",  # India
    "KR": "en",  # South Korea (English fallback)
}

# Phone country codes (leading digits of E.164 numbers) to country codes
# Only the most common ones; a full library like phonenumbers is recommended for production
PHONE_CC_TO_COUNTRY: dict[str, str] = {
    "1": "US",  # US, Canada, etc.
    "34": "ES",  # Spain
    "33": "FR",  # France
    "49": "DE",  # Germany
    "39": "IT",  # Italy
    "351": "PT",  # Portugal
    "48": "PL",  # Poland
    "31": "NL",  # Netherlands
    "44": "GB",  # United Kingdom
    "353": "IE",  # Ireland
    "43": "AT",  # Austria
    "32": "BE",  # Belgium
    "55": "BR",  # Brazil
    "52": "MX",  # Mexico
    "54": "AR",  # Argentina
    "56": "CL",  # Chile
    "57": "CO",  # Colombia
    "51": "PE",  # Peru
    "81": "JP",  # Japan
    "86": "CN",  # China
    "886": "TW",  # Taiwan
    "65": "SG",  # Singapore
    "91": "IN",  # India
}

SUPPORTED_LANGUAGES = frozenset({"en", "es", "fr", "de", "it", "pt", "pl", "nl", "ja", "zh"})

# Speech script templates organized by language
MULTILINGUAL_SPEECH_SCRIPTS: dict[str, dict[str, str]] = {
    "en": {
        "consent_prompt": (
            "Hello {name}. We call from {organization}. "
            "To confirm, press 1. To decline, press 2."
        ),
        "declined_prompt": "Verification declined. Goodbye.",
        "admin_send_code_instruction_prompt": (
            "Please wait while the administrator sends your verification code."
        ),
        "code_sent_prompt": (
            "Please enter your {code_length}-digit OTP verification code on your keypad."
        ),
        "pending_admin_verification_prompt": "Please wait for the administrator verification.",
        "approved_prompt": "Thank you for choosing our services.",
        "rejected_retry_prompt": (
            "Verification failed. Please repeat your {code_length}-digit verification code."
        ),
        "failed_prompt": "Verification failed. Please contact the administration.",
        "goodbye_prompt": "Goodbye.",
    },
    "es": {
        "consent_prompt": (
            "Hola {name}. Llamamos desde {organization}. "
            "Para confirmar, presione 1. Para rechazar, presione 2."
        ),
        "declined_prompt": "Verificación rechazada. Adiós.",
        "admin_send_code_instruction_prompt": (
            "Por favor espere mientras el administrador envía su código de verificación."
        ),
        "code_sent_prompt": (
            "Por favor ingrese su código de verificación OTP de {code_length} dígitos en el teclado."
        ),
        "pending_admin_verification_prompt": "Por favor espere la verificación del administrador.",
        "approved_prompt": "Gracias por elegir nuestros servicios.",
        "rejected_retry_prompt": (
            "Verificación fallida. Por favor repita su código de verificación de {code_length} dígitos."
        ),
        "failed_prompt": "Verificación fallida. Por favor contacte a la administración.",
        "goodbye_prompt": "Adiós.",
    },
    "fr": {
        "consent_prompt": (
            "Bonjour {name}. Nous appelons de {organization}. "
            "Pour confirmer, appuyez sur 1. Pour refuser, appuyez sur 2."
        ),
        "declined_prompt": "Vérification refusée. Au revoir.",
        "admin_send_code_instruction_prompt": (
            "Veuillez patienter pendant que l'administrateur envoie votre code de vérification."
        ),
        "code_sent_prompt": (
            "Veuillez entrer votre code de vérification OTP à {code_length} chiffres sur le clavier."
        ),
        "pending_admin_verification_prompt": "Veuillez attendre la vérification de l'administrateur.",
        "approved_prompt": "Merci d'avoir choisi nos services.",
        "rejected_retry_prompt": (
            "Vérification échouée. Veuillez entrer à nouveau votre code de vérification à {code_length} chiffres."
        ),
        "failed_prompt": "Vérification échouée. Veuillez contacter l'administration.",
        "goodbye_prompt": "Au revoir.",
    },
    "de": {
        "consent_prompt": (
            "Hallo {name}. Wir rufen von {organization} an. "
            "Zum Bestätigen drücken Sie 1. Zum Ablehnen drücken Sie 2."
        ),
        "declined_prompt": "Verifizierung abgelehnt. Auf Wiedersehen.",
        "admin_send_code_instruction_prompt": (
            "Bitte warten Sie, während der Administrator Ihren Verifizierungscode sendet."
        ),
        "code_sent_prompt": (
            "Bitte geben Sie Ihren {code_length}-stelligen OTP-Verifizierungscode auf der Tastatur ein."
        ),
        "pending_admin_verification_prompt": "Bitte warten Sie auf die Administratorverifizierung.",
        "approved_prompt": "Vielen Dank, dass Sie sich für unsere Dienstleistungen entschieden haben.",
        "rejected_retry_prompt": (
            "Verifizierung fehlgeschlagen. Bitte geben Sie Ihren {code_length}-stelligen Verifizierungscode erneut ein."
        ),
        "failed_prompt": "Verifizierung fehlgeschlagen. Bitte wenden Sie sich an die Verwaltung.",
        "goodbye_prompt": "Auf Wiedersehen.",
    },
    "it": {
        "consent_prompt": (
            "Ciao {name}. Chiamiamo da {organization}. "
            "Per confermare, premi 1. Per rifiutare, premi 2."
        ),
        "declined_prompt": "Verifica rifiutata. Arrivederci.",
        "admin_send_code_instruction_prompt": (
            "Per favore attendi mentre l'amministratore invia il tuo codice di verifica."
        ),
        "code_sent_prompt": (
            "Per favore inserisci il tuo codice OTP di verifica a {code_length} cifre sulla tastiera."
        ),
        "pending_admin_verification_prompt": "Per favore attendi la verifica dell'amministratore.",
        "approved_prompt": "Grazie per aver scelto i nostri servizi.",
        "rejected_retry_prompt": (
            "Verifica non riuscita. Per favore ripeti il tuo codice di verifica a {code_length} cifre."
        ),
        "failed_prompt": "Verifica non riuscita. Per favore contatta l'amministrazione.",
        "goodbye_prompt": "Arrivederci.",
    },
    "pt": {
        "consent_prompt": (
            "Olá {name}. Chamamos de {organization}. "
            "Para confirmar, pressione 1. Para recusar, pressione 2."
        ),
        "declined_prompt": "Verificação recusada. Adeus.",
        "admin_send_code_instruction_prompt": (
            "Por favor aguarde enquanto o administrador envia seu código de verificação."
        ),
        "code_sent_prompt": (
            "Por favor digite seu código OTP de verificação de {code_length} dígitos no teclado."
        ),
        "pending_admin_verification_prompt": "Por favor aguarde a verificação do administrador.",
        "approved_prompt": "Obrigado por escolher nossos serviços.",
        "rejected_retry_prompt": (
            "Verificação falhou. Por favor repita seu código de verificação de {code_length} dígitos."
        ),
        "failed_prompt": "Verificação falhou. Por favor contate a administração.",
        "goodbye_prompt": "Adeus.",
    },
    "pl": {
        "consent_prompt": (
            "Cześć {name}. Dzwonimy z {organization}. "
            "Aby potwierdzić, naciśnij 1. Aby odrzucić, naciśnij 2."
        ),
        "declined_prompt": "Weryfikacja odrzucona. Do widzenia.",
        "admin_send_code_instruction_prompt": (
            "Proszę czekać, podczas gdy administrator wysyła Twój kod weryfikacyjny."
        ),
        "code_sent_prompt": (
            "Proszę wpisz swój {code_length}-cyfrowy kod weryfikacyjny OTP na klawiaturze."
        ),
        "pending_admin_verification_prompt": "Proszę czekaj na weryfikację administratora.",
        "approved_prompt": "Dziękujemy za wybór naszych usług.",
        "rejected_retry_prompt": (
            "Weryfikacja nie powiodła się. Proszę powtórz swój {code_length}-cyfrowy kod weryfikacyjny."
        ),
        "failed_prompt": "Weryfikacja nie powiodła się. Proszę kontaktuj administrację.",
        "goodbye_prompt": "Do widzenia.",
    },
    "nl": {
        "consent_prompt": (
            "Hallo {name}. We bellen van {organization}. "
            "Druk op 1 om te bevestigen. Druk op 2 om af te wijzen."
        ),
        "declined_prompt": "Verificatie geweigerd. Tot ziens.",
        "admin_send_code_instruction_prompt": (
            "Wacht alstublieft terwijl de beheerder uw verificatiecode verstuurt."
        ),
        "code_sent_prompt": (
            "Voer alstublieft uw {code_length}-cijferige OTP-verificatiecode in op het toetsenbord."
        ),
        "pending_admin_verification_prompt": "Wacht alstublieft op verificatie door de beheerder.",
        "approved_prompt": "Dank u voor het kiezen van onze diensten.",
        "rejected_retry_prompt": (
            "Verificatie mislukt. Voer alstublieft uw {code_length}-cijferige verificatiecode opnieuw in."
        ),
        "failed_prompt": "Verificatie mislukt. Neem alstublieft contact op met de beheerder.",
        "goodbye_prompt": "Tot ziens.",
    },
    "ja": {
        "consent_prompt": (
            "こんにちは{name}さん。{organization}からの電話です。"
            "確認するには1を押してください。キャンセルするには2を押してください。"
        ),
        "declined_prompt": "認証がキャンセルされました。さようなら。",
        "admin_send_code_instruction_prompt": (
            "管理者が認証コードを送信するまでお待ちください。"
        ),
        "code_sent_prompt": (
            "{code_length}桁のOTP認証コードをキーパッドで入力してください。"
        ),
        "pending_admin_verification_prompt": "管理者の認証をお待ちください。",
        "approved_prompt": "当社のサービスをご利用いただきありがとうございます。",
        "rejected_retry_prompt": (
            "認証に失敗しました。{code_length}桁の認証コードをもう一度入力してください。"
        ),
        "failed_prompt": "認証に失敗しました。管理者にお問い合わせください。",
        "goodbye_prompt": "さようなら。",
    },
    "zh": {
        "consent_prompt": (
            "您好 {name}。我们来自 {organization}。"
            "要确认，请按 1。要拒绝，请按 2。"
        ),
        "declined_prompt": "验证已拒绝。再见。",
        "admin_send_code_instruction_prompt": (
            "请稍候，管理员正在发送您的验证码。"
        ),
        "code_sent_prompt": (
            "请在键盘上输入您的 {code_length} 位 OTP 验证码。"
        ),
        "pending_admin_verification_prompt": "请等待管理员验证。",
        "approved_prompt": "感谢您选择我们的服务。",
        "rejected_retry_prompt": (
            "验证失败。请重新输入您的 {code_length} 位验证码。"
        ),
        "failed_prompt": "验证失败。请联系管理员。",
        "goodbye_prompt": "再见。",
    },
}


def detect_language_from_phone(phone_e164: str) -> str:
    """
    Detect language from E.164 phone number by matching country code prefix.
    
    Args:
        phone_e164: Phone number in E.164 format (e.g. "+34912345678" for Spain)
    
    Returns:
        Language code (e.g. "es", "en"). Defaults to "en" if not detected.
    """
    if not phone_e164:
        return "en"
    
    # Remove leading + and spaces
    digits = "".join(ch for ch in phone_e164 if ch.isdigit())
    if not digits:
        return "en"
    
    # Try longest phone country code first (some are 1-3 digits)
    for cc_len in (3, 2, 1):
        prefix = digits[:cc_len]
        if prefix in PHONE_CC_TO_COUNTRY:
            country = PHONE_CC_TO_COUNTRY[prefix]
            lang = COUNTRY_CODE_TO_LANGUAGE.get(country, "en")
            if lang in SUPPORTED_LANGUAGES:
                return lang
    
    return "en"


def get_speech_scripts_for_language(language: str) -> dict[str, str]:
    """
    Get speech script templates for a specific language.
    
    Args:
        language: Language code (e.g. "es", "en")
    
    Returns:
        Dictionary of script key → template text. Defaults to English if not found.
    """
    if language in MULTILINGUAL_SPEECH_SCRIPTS:
        return MULTILINGUAL_SPEECH_SCRIPTS[language]
    return MULTILINGUAL_SPEECH_SCRIPTS["en"]


def normalize_language_code(lang: Optional[str]) -> str:
    """Normalize language code, returning valid supported language or 'en' default."""
    if not lang:
        return "en"
    normalized = str(lang).strip().lower()
    if normalized in SUPPORTED_LANGUAGES:
        return normalized
    return "en"

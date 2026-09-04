"""Pruebas unitarias para el validador de protección SSRF (SSRFValidator)."""

import pytest

from app.security.ssrf import (
    SSRFValidationError,
    SSRFValidator,
    get_ssrf_validator,
)


class TestSSRFValidatorIPs:
    """Pruebas de validación de direcciones IP directas frente a listas negras y blancas."""

    def test_blocks_loopback_ipv4(self) -> None:
        validator = SSRFValidator()
        for ip in ["127.0.0.1", "127.0.0.2", "127.1.2.3"]:
            is_valid, reason = validator.validate_ip(ip)
            assert not is_valid
            assert reason is not None
            assert "bloqueada" in reason.lower()

    def test_blocks_loopback_ipv6(self) -> None:
        validator = SSRFValidator()
        is_valid, reason = validator.validate_ip("::1")
        assert not is_valid
        assert reason is not None

    def test_blocks_cloud_metadata_ips(self) -> None:
        validator = SSRFValidator()
        # AWS / GCP / Azure Instance Metadata Service
        for ip in ["169.254.169.254", "169.254.169.250", "169.254.1.1"]:
            is_valid, reason = validator.validate_ip(ip)
            assert not is_valid
            assert reason is not None
            assert "169.254.0.0/16" in reason

    def test_blocks_rfc1918_private_ips(self) -> None:
        validator = SSRFValidator()
        private_ips = [
            "10.0.0.1",
            "10.255.255.254",
            "172.16.0.1",
            "172.31.255.254",
            "192.168.0.1",
            "192.168.1.100",
            "0.0.0.0",
        ]
        for ip in private_ips:
            is_valid, reason = validator.validate_ip(ip)
            assert not is_valid, f"La IP {ip} debería haber sido bloqueada"
            assert reason is not None

    def test_allows_public_ips(self) -> None:
        validator = SSRFValidator()
        public_ips = ["8.8.8.8", "1.1.1.1", "93.184.216.34"]
        for ip in public_ips:
            is_valid, reason = validator.validate_ip(ip)
            assert is_valid
            assert reason is None

    def test_allow_private_networks_configuration(self) -> None:
        # Si se autorizan redes privadas, RFC 1918 pasa, pero loopback y metadata siguen bloqueadas
        validator = SSRFValidator(allow_private_networks=True)
        assert validator.validate_ip("192.168.1.1")[0] is True
        assert validator.validate_ip("10.0.0.5")[0] is True

        # Loopback y Metadata SIEMPRE deben ser bloqueados
        assert validator.validate_ip("127.0.0.1")[0] is False
        assert validator.validate_ip("169.254.169.254")[0] is False

    def test_explicit_allowed_networks(self) -> None:
        # Permitir explícitamente una subred privada
        validator = SSRFValidator(allowed_networks=["10.50.0.0/16"])
        # Esta subred permitida debe pasar
        assert validator.validate_ip("10.50.1.20")[0] is True
        # Otra subred privada sigue bloqueada
        assert validator.validate_ip("10.60.1.20")[0] is False


class TestSSRFValidatorURLs:
    """Pruebas de validación de URLs completas."""

    def test_blocks_forbidden_schemes(self) -> None:
        validator = SSRFValidator()
        forbidden_urls = [
            "file:///etc/passwd",
            "ftp://files.internal/doc",
            "gopher://127.0.0.1:70",
            "dict://127.0.0.1:11211",
        ]
        for url in forbidden_urls:
            is_valid, reason = validator.validate_url(url, resolve_dns=False)
            assert not is_valid
            assert reason is not None
            assert "protocolo" in reason.lower()

    def test_blocks_localhost_and_internal_hostnames(self) -> None:
        validator = SSRFValidator()
        blocked_urls = [
            "http://localhost/admin",
            "http://localhost:8080/api",
            "http://metadata.google.internal/computeMetadata/v1",
            "http://service.internal/status",
            "http://myhost.local/info",
        ]
        for url in blocked_urls:
            is_valid, reason = validator.validate_url(url, resolve_dns=False)
            assert not is_valid
            assert reason is not None

    def test_blocks_literal_ip_urls(self) -> None:
        validator = SSRFValidator()
        assert (
            validator.validate_url("http://127.0.0.1:8000/metrics", resolve_dns=False)[0] is False
        )
        assert (
            validator.validate_url("http://169.254.169.254/latest/meta-data/", resolve_dns=False)[0]
            is False
        )
        assert validator.validate_url("http://10.0.0.1/secrets", resolve_dns=False)[0] is False

    def test_allows_public_url(self) -> None:
        validator = SSRFValidator()
        # Sin resolver DNS para tests rápidos
        is_valid, reason = validator.validate_url("https://api.github.com/repos", resolve_dns=False)
        assert is_valid
        assert reason is None

    def test_allowlist_hostnames(self) -> None:
        validator = SSRFValidator(allowed_hosts=["api.cabocom.net", "*.partner.org"])

        # Hosts en allowlist pasan de inmediato
        assert (
            validator.validate_url("https://api.cabocom.net/v1/data", resolve_dns=False)[0] is True
        )
        assert (
            validator.validate_url("https://auth.partner.org/token", resolve_dns=False)[0] is True
        )

    def test_assert_safe_url_raises(self) -> None:
        validator = SSRFValidator()
        with pytest.raises(SSRFValidationError) as exc_info:
            validator.assert_safe_url("http://127.0.0.1:9090", resolve_dns=False)
        assert exc_info.value.target == "http://127.0.0.1:9090"

    def test_is_safe_url_boolean(self) -> None:
        validator = SSRFValidator()
        assert validator.is_safe_url("http://127.0.0.1:80", resolve_dns=False) is False
        assert validator.is_safe_url("https://europapress.es/rss", resolve_dns=False) is True


class TestSSRFValidatorToolArguments:
    """Pruebas de inspección de argumentos en invocaciones de tools."""

    def test_detects_malicious_url_in_tool_args(self) -> None:
        validator = SSRFValidator()
        args = {
            "query": "Consultar metadata de AWS",
            "target_url": "http://169.254.169.254/latest/meta-data/",
        }
        is_safe, reason = validator.validate_tool_arguments_for_ssrf(
            tool_name="http_requester",
            args=args,
            makes_http_requests=True,
        )
        assert not is_safe
        assert reason is not None
        assert "target_url" in reason

    def test_detects_raw_private_ip_in_tool_args(self) -> None:
        validator = SSRFValidator()
        args = {"host": "127.0.0.1", "port": 8080}
        is_safe, reason = validator.validate_tool_arguments_for_ssrf(
            tool_name="port_checker",
            args=args,
            makes_http_requests=True,
        )
        assert not is_safe
        assert reason is not None
        assert "127.0.0.1" in reason

    def test_allows_benign_tool_args(self) -> None:
        validator = SSRFValidator()
        args = {"city": "Madrid", "units": "metric"}
        is_safe, reason = validator.validate_tool_arguments_for_ssrf(
            tool_name="weather_tool",
            args=args,
            makes_http_requests=True,
        )
        assert is_safe
        assert reason is None


def test_singleton_factory() -> None:
    v1 = get_ssrf_validator()
    v2 = get_ssrf_validator()
    assert v1 is v2
    assert isinstance(v1, SSRFValidator)

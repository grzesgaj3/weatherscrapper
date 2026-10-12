import io
import unittest
from unittest.mock import Mock

from uart_scraper import InvalidMeasurement, WeatherApi, parse_measurement, process_line


SAMPLE = "MW,t=23.41,h=48.20,p=1012.55,r=12,ra=901,mq=387,aht=1,bmp=1\r\n"


class ParserTests(unittest.TestCase):
    def test_parses_uart_format(self) -> None:
        self.assertEqual(
            parse_measurement(SAMPLE),
            {
                "t": 23.41,
                "h": 48.20,
                "p": 1012.55,
                "r": 12.0,
                "ra": 901,
                "mq": 387,
                "aht": True,
                "bmp": True,
            },
        )

    def test_rejects_missing_field(self) -> None:
        with self.assertRaises(InvalidMeasurement):
            parse_measurement("MW,t=23.41,h=48.20")

    def test_rejects_invalid_boolean(self) -> None:
        with self.assertRaises(InvalidMeasurement):
            parse_measurement(SAMPLE.replace("aht=1", "aht=maybe"))


class SendingTests(unittest.TestCase):
    def test_posts_json_with_api_key(self) -> None:
        session = Mock()
        session.post.return_value.status_code = 201
        session.headers = {}
        api = WeatherApi("http://api.test/measurements/", "secret", 3, session)
        output = io.StringIO()

        self.assertTrue(process_line(SAMPLE.encode("ascii"), api, output))
        session.post.assert_called_once()
        self.assertEqual(session.post.call_args.kwargs["json"]["aht"], True)
        self.assertEqual(session.headers["X-API-Key"], "secret")
        self.assertEqual(output.getvalue(), "sent\n")


if __name__ == "__main__":
    unittest.main()

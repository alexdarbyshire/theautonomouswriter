import base64
from unittest.mock import MagicMock, patch

from agent.images import (
    _build_image_prompt,
    _generate_all,
    _generate_one,
    _judge_best,
    generate_cover_image,
)

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
FAKE_B64 = base64.b64encode(FAKE_PNG).decode()
FAKE_DATA_URL = f"data:image/png;base64,{FAKE_B64}"


def _mock_image_response(data_url=FAKE_DATA_URL):
    """Create a mock OpenAI response with an image."""
    img = MagicMock()
    img.image_url.url = data_url
    msg = MagicMock()
    msg.images = [img]
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class TestBuildImagePrompt:
    def test_returns_prompt_string(self):
        llm = MagicMock()
        llm._call.return_value = "A misty cathedral at dawn"
        result = _build_image_prompt(llm, "My Title", "My description", "contemplative")
        assert result == "A misty cathedral at dawn"
        llm._call.assert_called_once()


class TestGenerateOne:
    @patch("agent.images.OpenAI")
    def test_success(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_image_response()

        result = _generate_one("fake-key", "test-model", "a prompt")
        assert result is not None
        model, img_bytes = result
        assert model == "test-model"
        assert img_bytes == FAKE_PNG

    @patch("agent.images.OpenAI")
    def test_failure_returns_none(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API error")

        result = _generate_one("fake-key", "test-model", "a prompt")
        assert result is None


class TestGenerateAll:
    @patch("agent.images._generate_one")
    def test_collects_successes(self, mock_gen):
        mock_gen.side_effect = [
            ("model-a", FAKE_PNG),
            None,
            ("model-c", FAKE_PNG),
        ]
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake"}):
            results = _generate_all("a prompt")
        assert len(results) == 2

    @patch("agent.images._generate_one")
    def test_all_fail(self, mock_gen):
        mock_gen.return_value = None
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake"}):
            results = _generate_all("a prompt")
        assert len(results) == 0


class TestJudgeBest:
    def test_selects_chosen_image(self):
        llm = MagicMock()
        judge_msg = MagicMock()
        judge_msg.content = "2"
        judge_choice = MagicMock()
        judge_choice.message = judge_msg
        judge_resp = MagicMock()
        judge_resp.choices = [judge_choice]
        llm.client.chat.completions.create.return_value = judge_resp

        img_a = b"image-a-bytes"
        img_b = b"image-b-bytes"
        candidates = [("model-a", img_a), ("model-b", img_b)]

        result = _judge_best(llm, candidates, "Title", "Description")
        assert result == img_b

    def test_falls_back_to_first_on_parse_error(self):
        llm = MagicMock()
        llm.client.chat.completions.create.side_effect = Exception("vision failed")

        img_a = b"image-a-bytes"
        img_b = b"image-b-bytes"
        candidates = [("model-a", img_a), ("model-b", img_b)]

        result = _judge_best(llm, candidates, "Title", "Description")
        assert result == img_a


class TestGenerateCoverImage:
    def test_disabled_returns_none(self):
        with patch.dict("os.environ", {"ENABLE_IMAGES": "false"}):
            result = generate_cover_image(MagicMock(), "T", "D", "M")
        assert result is None

    @patch("agent.images._generate_all")
    @patch("agent.images._build_image_prompt")
    def test_single_candidate_skips_judge(self, mock_prompt, mock_gen_all):
        mock_prompt.return_value = "a prompt"
        mock_gen_all.return_value = [("model-a", FAKE_PNG)]

        with patch.dict("os.environ", {"ENABLE_IMAGES": "true"}):
            result = generate_cover_image(MagicMock(), "Title", "Desc", "mood")
        assert result == FAKE_PNG

    @patch("agent.images._judge_best")
    @patch("agent.images._generate_all")
    @patch("agent.images._build_image_prompt")
    def test_multiple_candidates_uses_judge(self, mock_prompt, mock_gen_all, mock_judge):
        mock_prompt.return_value = "a prompt"
        img_a, img_b = b"img-a", b"img-b"
        mock_gen_all.return_value = [("model-a", img_a), ("model-b", img_b)]
        mock_judge.return_value = img_b

        with patch.dict("os.environ", {"ENABLE_IMAGES": "true"}):
            result = generate_cover_image(MagicMock(), "Title", "Desc", "mood")
        assert result == img_b
        mock_judge.assert_called_once()

    @patch("agent.images._generate_all")
    @patch("agent.images._build_image_prompt")
    def test_all_fail_returns_none(self, mock_prompt, mock_gen_all):
        mock_prompt.return_value = "a prompt"
        mock_gen_all.return_value = []

        with patch.dict("os.environ", {"ENABLE_IMAGES": "true"}):
            result = generate_cover_image(MagicMock(), "Title", "Desc", "mood")
        assert result is None

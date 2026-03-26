import unittest

from aiohttp.test_utils import AioHTTPTestCase

from server import create_app


class FlipOffServerTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_get_message_returns_default_state(self):
        response = await self.client.get('/api/message')
        self.assertEqual(response.status, 200)

        payload = await response.json()
        self.assertEqual(
            payload,
            {
                'hasOverride': False,
                'lines': ['', '', '', '', ''],
                'updatedAt': None,
            },
        )

    async def test_post_message_wraps_and_centers_single_string(self):
        response = await self.client.post(
            '/api/message',
            json={'message': 'hello from the backend api'},
        )
        self.assertEqual(response.status, 200)

        payload = await response.json()
        self.assertTrue(payload['hasOverride'])
        self.assertEqual(
            payload['lines'],
            ['', 'HELLO FROM THE', 'BACKEND API', '', ''],
        )
        self.assertIsNotNone(payload['updatedAt'])

    async def test_post_lines_pads_to_full_board_height(self):
        response = await self.client.post(
            '/api/message',
            json={'lines': ['hello world', 'remote mode']},
        )
        self.assertEqual(response.status, 200)

        payload = await response.json()
        self.assertEqual(
            payload['lines'],
            ['HELLO WORLD', 'REMOTE MODE', '', '', ''],
        )

    async def test_post_rejects_overlong_lines(self):
        response = await self.client.post(
            '/api/message',
            json={'lines': ['X' * 19]},
        )
        self.assertEqual(response.status, 400)

        payload = await response.json()
        self.assertEqual(payload['error'], 'Line 1 exceeds 18 characters.')

    async def test_post_rejects_message_that_cannot_fit(self):
        response = await self.client.post(
            '/api/message',
            json={
                'message': (
                    'alpha bravo charlie delta echo foxtrot golf hotel india juliet '
                    'kilo lima mike november oscar papa quebec romeo sierra tango '
                    'uniform victor whiskey xray yankee zulu'
                )
            },
        )
        self.assertEqual(response.status, 400)

        payload = await response.json()
        self.assertEqual(
            payload['error'],
            "'message' must fit within 5 lines of 18 characters.",
        )

    async def test_delete_message_clears_override(self):
        await self.client.post('/api/message', json={'lines': ['remote message']})

        response = await self.client.delete('/api/message')
        self.assertEqual(response.status, 200)

        payload = await response.json()
        self.assertEqual(
            payload,
            {
                'hasOverride': False,
                'lines': ['', '', '', '', ''],
                'updatedAt': None,
            },
        )

    async def test_websocket_receives_create_and_clear_events(self):
        ws = await self.client.ws_connect('/ws')

        initial_event = await ws.receive_json()
        self.assertEqual(initial_event['type'], 'message_state')
        self.assertFalse(initial_event['payload']['hasOverride'])

        create_response = await self.client.post(
            '/api/message',
            json={'lines': ['live update']},
        )
        self.assertEqual(create_response.status, 200)

        created_event = await ws.receive_json()
        self.assertTrue(created_event['payload']['hasOverride'])
        self.assertEqual(
            created_event['payload']['lines'],
            ['LIVE UPDATE', '', '', '', ''],
        )

        clear_response = await self.client.delete('/api/message')
        self.assertEqual(clear_response.status, 200)

        cleared_event = await ws.receive_json()
        self.assertFalse(cleared_event['payload']['hasOverride'])
        self.assertEqual(cleared_event['payload']['lines'], ['', '', '', '', ''])

        await ws.close()


if __name__ == '__main__':
    unittest.main()

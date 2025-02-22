import http.server
import socketserver
import json

PORT = 11434

class LLMRequestHandler(http.server.BaseHTTPRequestHandler):
    def _send_response(self, message, status_code=200):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(message).encode('utf-8'))

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        try:
            request_json = json.loads(post_data.decode('utf-8')) #parse incoming JSON
            #print(f"received: {request_json}") #for debugging

            response_data = {
                "id": "chatcmpl-fake-id",
                "object": "chat.completion",
                "created": 1677652288,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello world"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15
                }
            }
            self._send_response(response_data)

        except json.JSONDecodeError:
            self._send_response({"error": "Invalid JSON"}, 400)
        except Exception as e:
            self._send_response({"error": str(e)}, 500)

    def do_GET(self): #add a simple GET method for health check
        self._send_response({"status": "ok"})

with socketserver.TCPServer(("localhost", PORT), LLMRequestHandler) as httpd:
    print(f"Serving at port {PORT}")
    httpd.serve_forever()
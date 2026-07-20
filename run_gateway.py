from http.server import ThreadingHTTPServer

import gateway


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", gateway.PORT), gateway.H).serve_forever()


if __name__ == "__main__":
    main()

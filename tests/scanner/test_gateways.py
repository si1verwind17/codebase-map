"""Gateway routes read from proxy and gateway configs (nginx, Spring Cloud Gateway, Envoy, YARP)."""
from vizcode import structure

FILES = {
    "web/default.conf.template": "server {\n    listen 8080;\n    location / {\n        root /usr/share/nginx/html;\n    }\n"
                                 "    #location /old/ {\n    #    proxy_pass http://old;\n    #}\n"
                                 "    location /api/cart/ {\n        proxy_pass http://${CART_HOST}:8080/;\n    }\n"
                                 "    location /api/user {\n        proxy_pass http://admin:s3/cr@t@user:8080;\n    }\n}\n",
    "gateway/src/main/resources/application.yml":
        "spring:\n  cloud:\n    gateway:\n      routes:\n        - id: vets\n          uri: lb://vets-service\n"
        "          predicates:\n            - Path=/api/vet/**\n          filters:\n            - StripPrefix=2\n"
        "        - id: shop\n          uri: http://shop:9000\n          predicates:\n            - Path=/shop/**,/store/**\n",
    "gateway/src/test/resources/application-test.yml":
        "spring:\n  cloud:\n    gateway:\n      routes:\n        - id: t\n          uri: lb://t\n          predicates:\n"
        "            - Path=/t/**\n",
    "proxy/envoy.yaml": "static_resources:\n  listeners:\n    - filter_chains:\n        - filters:\n"
                        "            - typed_config:\n                route_config:\n                  virtual_hosts:\n"
                        "                    - routes:\n                        - match: { prefix: \"/loadgen/\" }\n"
                        "                          route: { cluster: loadgen, prefix_rewrite: \"/\" }\n"
                        "                        - match:\n                            prefix: \"/\"\n"
                        "                          route:\n                            cluster: frontend\n"
                        "  clusters:\n    - name: frontend\n      load_assignment:\n        endpoints:\n"
                        "          - lb_endpoints:\n              - endpoint:\n                  address:\n"
                        "                    socket_address:\n                      address: frontend\n"
                        "                      port_value: 8080\n",
    "Gateway/appsettings.json": '{\n  "ReverseProxy": {\n    "Routes": {\n      "orders": {\n        "ClusterId": "ordersc",\n'
                                '        "Match": { "Path": "/orders/{**rest}" }\n      }\n    },\n    "Clusters": {\n'
                                '      "ordersc": { "Destinations": { "d1": { "Address": "http://ordering-api/" } } }\n'
                                '    }\n  }\n}\n',
    "app.py": "def main():\n    pass\n",
}


def test_gateway_routes_of_each_config_kind(make_repo):
    s = structure.build(make_repo(FILES))
    got = [(g["kind"], g["prefix"], g["target"], g["rewrite"], f"{g['file']}:{g['line']}") for g in s["gateways"]]
    assert got == [
        ("yarp", "/orders", "ordering-api", None, "Gateway/appsettings.json:4"),
        ("spring-gateway", "/api/vet", "vets-service", "/", "gateway/src/main/resources/application.yml:5"),
        ("spring-gateway", "/shop", "shop:9000", None, "gateway/src/main/resources/application.yml:11"),
        ("spring-gateway", "/store", "shop:9000", None, "gateway/src/main/resources/application.yml:11"),
        ("envoy", "/loadgen/", "loadgen", "/", "proxy/envoy.yaml:9"),
        ("envoy", "/", "frontend:8080", None, "proxy/envoy.yaml:12"),
        ("nginx", "/api/cart/", "${CART_HOST}:8080", "/", "web/default.conf.template:9"),
        ("nginx", "/api/user", "user:8080", None, "web/default.conf.template:12")]
    md = structure.summary_md(s)
    assert "## Gateway routes — 8" in md and "- /api/vet → vets-service (gateway/src/main/resources/application.yml:5, " \
        "spring-gateway, rewrite /)" in md
    assert "s3/cr" not in md and "cr@t" not in md


def test_gateway_configs_that_broke_the_readers(make_repo):
    files = {
        "a/nginx.conf": "server {\n  location /api/ {\n    proxy_set_header Host ${API_HOST};\n"
                        "    proxy_pass http://backend/x?api_key=SECRETVALUE;\n  }\n"
                        "  location /b/ {\n    proxy_pass http://b?token=SECRETVALUE;\n  }\n}\n",
        "g/src/main/resources/application.yml": "spring:\n  cloud:\n    gateway:\n      routes:\n        - id: v\n"
                                                 "          uri: lb://vets # the vets service\n          predicates:\n"
                                                 "            - Path=/vet/**\n",
        "Gw/appsettings.json": '﻿{\n  // the proxy\n  "ReverseProxy": {\n    "Clusters": { "orders": { "Destinations": '
                               '{ "d": { "Address": "http://ordering/" } } } },\n    "Routes": {\n      "orders": {\n'
                               '        "ClusterId": "orders", "Match": { "Path": "/o/{**r}" } }\n    }\n  }\n}\n',
        "Gw2/appsettings.Development.json": '{"ReverseProxy": {"Routes": [{"RouteId": "x"}], "Clusters": ["y"]}}\n',
        "Gw3/appsettings.json": '{"ReverseProxy": {"Routes": {"x": "nope", "y": {"Match": "z"}}}}\n',
        "app.py": "def main():\n    pass\n"}
    s = structure.build(make_repo(files))
    got = [(g["kind"], g["prefix"], g["target"], g["rewrite"], g["line"]) for g in s["gateways"]]
    assert got == [("yarp", "/o", "ordering", None, 6), ("nginx", "/api/", "backend", "/x", 2),
                   ("nginx", "/b/", "b", None, 6), ("spring-gateway", "/vet", "vets", None, 5)]
    assert "SECRETVALUE" not in structure.summary_md(s)

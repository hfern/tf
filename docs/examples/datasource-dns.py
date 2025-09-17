from typing import Optional

import requests

from tf.iface import Config, DataSource, ReadDataContext, State


class DnsResolver(DataSource):
    ...

    def read(self, ctx: ReadDataContext, config: Config) -> Optional[State]:
        hostname = config["hostname"]
        typ = config.get("type", "A")

        resp = requests.get(f"https://dns.google/resolve?name={hostname}&type={typ}").json()
        answer = resp.get("Answer")

        if not answer:
            ctx.diagnostics.add_error(
                summary="No DNS records found",
                detail=f"No {typ} records found for {hostname}",
                path=["hostname"],
            )
            return None

        return {
            **config,
            "data": answer[0]["data"],
            "ttl": answer[0]["TTL"],
        }

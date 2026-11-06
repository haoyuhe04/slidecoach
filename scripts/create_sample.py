from pathlib import Path
from pptx import Presentation

root = Path(__file__).resolve().parent.parent
(root / "sample").mkdir(exist_ok=True)
prs = Presentation()
pages = [
    ("TCP 三次握手与双方确认", "TCP 建立连接时，双方交换并确认各自的初始序列号。客户端先发送 SYN，服务端回复 SYN + ACK，客户端最后发送 ACK。第二次报文确认客户端的 SYN，同时携带服务端的 SYN；第三次报文确认服务端的 SYN。两次 ACK 确认的对象不同。\n来源：RFC 9293 第 3.4.1、3.5 节。"),
    ("SYN 与确认号", "SYN 占用一个序列号。假设客户端初始序列号为 100，服务端为 300：第一次 SYN 的 seq=100；第二次 SYN+ACK 的 seq=300、ack=101；第三次 ACK 的 seq=101、ack=301。不带数据的 ACK 本身不占用序列号。\n来源：RFC 9293 第 3.5 节 Figure 6。"),
    ("复习时解释确认的对象", "解释第三次确认时，需要区分双方视角。客户端收到 SYN+ACK，已经看到服务端的 SYN 和对自己 SYN 的确认；服务端需要收到客户端对自己 SYN 的确认，才能完成这次握手。回答时应说明报文方向、确认对象和相应序列号，不只背诵三条报文的顺序。\n这是根据 RFC 9293 整理的教学样例，非用户真实课件。"),
]
for title, body in pages:
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    slide.placeholders[1].text = body
prs.save(root / "sample" / "TCP复习示例.pptx")
print("Created teaching sample (3 slides)")

import os
# 安装依赖（仅在需要时）
# os.system('pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host=mirrors.aliyun.com')

import sys
import random
from typing import Sequence, Mapping, Any, Union
import torch
import gradio as gr
from PIL import Image
import numpy as np
from io import BytesIO
import base64
from modelscope import ZImagePipeline # 新模型导入方式

# ========== 辅助函数（保持不变，仅保留需要用到的）==========
def get_value_at_index(obj: Union[Sequence, Mapping], index: int) -> Any:
    try:
        return obj[index]
    except KeyError:
        return obj["result"][index]

def find_path(name: str, path: str = None) -> str:
    if path is None:
        path = os.getcwd()
    if name in os.listdir(path):
        path_name = os.path.join(path, name)
        print(f"{name} found: {path_name}")
        return path_name
    parent_directory = os.path.dirname(path)
    if parent_directory == path:
        return None
    return find_path(name, parent_directory)

# ========== 模型加载（带缓存）========== 
# 移除了 ComfyUI 相关的 NODE_CLASS_MAPPINGS 和加载逻辑
_cached_pipe = None

def preload_models():
    """在服务启动时预加载并缓存 Z-Image 模型"""
    global _cached_pipe
    if _cached_pipe is None:
        print("Loading Z-Image model...")
        _cached_pipe = ZImagePipeline.from_pretrained(
            "Tongyi-MAI/Z-Image", # 替换为新模型 ID
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=False,
        )
        _cached_pipe.to("cuda") # 假设使用 GPU
        print("✅ Z-Image model preloaded and cached.")

# ========== 尺寸映射（保持不变）==========
ASPECT_RATIOS = {
    "1:1": (1, 1),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "16:9": (16, 9),
    "9:16": (9, 16),
    "21:9": (21, 9),
    "9:21": (9, 21),
}

def get_size_from_ratio(ratio: str, max_side=1024):
    w_ratio, h_ratio = ASPECT_RATIOS[ratio]
    if w_ratio >= h_ratio:
        width = max_side
        height = int(max_side * h_ratio / w_ratio)
    else:
        height = max_side
        width = int(max_side * w_ratio / h_ratio)
    # Z-Image 模型通常需要特定的分辨率，这里简单对齐到 64 的倍数
    width = (width // 64) * 64 
    height = (height // 64) * 64
    return width, height

# ========== 核心推理函数（替换为新模型逻辑）==========
def generate_image(prompt: str, aspect_ratio: str):
    global _cached_pipe
    width, height = get_size_from_ratio(aspect_ratio)
    print(f"Generating image with size: {width}x{height}")
    
    # 确保模型已加载
    if _cached_pipe is None:
        preload_models()
    
    # 新模型推理逻辑
    with torch.inference_mode():
        try:
            image = _cached_pipe(
                prompt=prompt,
                negative_prompt="", # 可根据需要添加
                height=height,
                width=width,
                cfg_normalization=False,
                num_inference_steps=50, # 保持与示例一致
                guidance_scale=4,
                generator=torch.Generator("cuda").manual_seed(random.randint(1, 2**64)),
            ).images[0]
            
            # 如果返回的是 PIL.Image，直接返回；如果是 Tensor，转换一下
            if isinstance(image, torch.Tensor):
                image = image.cpu().numpy()
                image = np.clip(image * 255.0, 0, 255).astype(np.uint8)
                image = Image.fromarray(image)
                
            return image
        except Exception as e:
            print(f"Generation error: {e}")
            raise

############################################################################################################################
# ========== 以下为提示词优化器逻辑（保持不变）==========
from openai import OpenAI

def create_client(token: str):
    if not token or token.strip() == "":
        raise ValueError("请先输入有效的 ModelScope Token！可在如下地址获取：https://www.modelscope.cn/my/myaccesstoken")
    return OpenAI(
        base_url='https://api-inference.modelscope.cn/v1',
        api_key=token.strip(),
    )

# ======================== 
# 带完整示例的系统提示（Few-Shot Prompting）
# ======================== 
SYSTEM_PROMPT_WITH_EXAMPLES = """
你是一位专业的AI图像提示词优化师，请将用户提供的原始提示词及后续修改指令，在**完全保留其核心意图的前提下**，融合所有信息，输出一段高质量、结构完整、细节丰富的自然语言提示词。
【优化规则】
1. 忠于原意：不得改变主体、动作、场景或风格方向。
2. 结构顺序：【主体与姿态】→【环境与背景】→【光影与氛围】→【艺术风格】→【画质与细节】。
3. 增强细节：明确材质（如“织锦缎”“磨砂金属”）、光源（如“低角度夕阳”）、色彩、空间关系。
4. 避免抽象词：用“丝绸光泽”代替“好看”，用“8K超精细”代替“高清”。
5. 输出为一段连续自然语言（无符号、无列表），≤800字。
【参考示例】
... (此处省略具体示例内容以保持代码简洁，保留原文件中的完整内容) ...
"""
# 注意：此处为了代码简洁省略了具体的示例文本，实际使用请保留原文件中的完整 SYSTEM_PROMPT_WITH_EXAMPLES 内容

# ======================== 
# 任务配置
# ======================== 
TASK_CONFIG = { 
    "optimize_prompt": { 
        "name": "优化文生图提示词", 
        "system_prompt": SYSTEM_PROMPT_WITH_EXAMPLES, 
        "use_history_as_chat": False, 
    }, 
    "chat": { 
        "name": "聊天", 
        "system_prompt": None, 
        "use_history_as_chat": True, 
    } 
} 

def extract_user_intent_for_optimize(history):
    user_messages = [msg for msg in history if msg is not None]
    if not user_messages:
        return ""
    if len(user_messages) == 1:
        return user_messages
    else:
        parts = [f"原始提示词：{user_messages}"]
        for i, msg in enumerate(user_messages[1:], start=1):
            parts.append(f"修改指令 {i}：{msg}")
        return "；".join(parts)

def build_messages(task_id: str, history):
    config = TASK_CONFIG[task_id]
    if config["use_history_as_chat"]:
        messages = []
        for user_msg, bot_msg in history:
            if user_msg is not None:
                messages.append({"role": "user", "content": user_msg})
            if bot_msg is not None:
                messages.append({"role": "assistant", "content": bot_msg})
        return messages
    else:
        full_intent = extract_user_intent_for_optimize(history)
        messages = []
        if config["system_prompt"]:
            messages.append({"role": "system", "content": config["system_prompt"]})
        if full_intent.strip():
            messages.append({"role": "user", "content": full_intent})
        else:
            messages.append({"role": "user", "content": "请优化以下提示词："}) 
        return messages

def generate_stream(client, model_name: str, messages: list):
    extra_body = {"enable_thinking": False}
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        stream=True,
        extra_body=extra_body
    )
    full_answer = ""
    for chunk in response:
        if chunk.choices:
            content = getattr(chunk.choices.delta, 'content', '') or ''
            if content:
                full_answer += content
                yield full_answer

def user(msg, history, task_id, max_turns):
    # 自动截断历史（保留最近 max_turns 轮）
    new_history = (history + [[msg, None]])[-max_turns:]
    return "", new_history, task_id

def chat(token, model_name, history, task_id, max_turns):
    if not history or history[-1] is not None:
        return history
    try:
        client = create_client(token)
        messages = build_messages(task_id, history)
        if task_id == "optimize_prompt" and not any(msg for msg in history if msg):
            history[-1] = "请输入提示词。"
            yield history
            return
    except Exception as e:
        history[-1] = f"错误：{str(e)}"
        yield history
        return
        
    history[-1] = ""
    yield history
    full_response = ""
    try:
        for partial in generate_stream(client, model_name, messages):
            full_response = partial
            history[-1] = full_response
            yield history
    except Exception as e:
        history[-1] = f"API 错误：{str(e)}"
        yield history

#########################################################################################################################
# ========== 新增：图像编辑功能（保持不变）==========
import os
import uuid
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import requests
import time
import json
from PIL import Image
from io import BytesIO

# 创建上传目录（用于保存用户上传的图片）
UPLOAD_IMAGE_DIR = Path("uploaded_images")
UPLOAD_IMAGE_DIR.mkdir(exist_ok=True)

# 公网可访问的图片基础 URL（根据你的部署信息）
PUBLIC_IMAGE_BASE_URL = "https://gswyhq-z-image.ms.show/images"


def _pil_to_rgb(im: Image.Image) -> Image.Image:
    """云端返回的 PNG 常含 alpha；直接 convert('RGB') 会使透明区域变黑。"""
    if im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        return bg
    if im.mode == "LA":
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        return bg
    if im.mode == "P" and "transparency" in im.info:
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        return bg
    return im.convert("RGB")


def edit_image_via_modelscope(model_name: str, prompt: str, local_image_paths: list, user_token: str) -> Image.Image:
    """ 使用用户提供的 Token 调用 ModelScope 图像编辑 API """
    if not user_token or not user_token.strip():
        raise ValueError("请先输入有效的 ModelScope Token！")
    
    # 构造公网可访问的图片 URL
    image_urls = [f"{PUBLIC_IMAGE_BASE_URL}/{os.path.basename(p)}" for p in local_image_paths]
    print(f"[图像编辑] 提示词: {prompt}")
    print(f"[图像编辑] 图片公网 URL 列表: {image_urls}")
    
    api_base = 'https://api-inference.modelscope.cn/'
    headers = { 
        "Authorization": f"Bearer {user_token.strip()}", 
        "Content-Type": "application/json", 
    }
    payload = { 
        "model": model_name, 
        "prompt": prompt, 
        "image_url": image_urls 
    }
    
    # 提交异步任务
    try:
        response = requests.post( 
            f"{api_base}v1/images/generations", 
            headers={**headers, "X-ModelScope-Async-Mode": "true"}, 
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8') 
        )
        response.raise_for_status()
        task_id = response.json()["task_id"]
        print(f"[图像编辑] 任务提交成功，task_id: {task_id}")
    except Exception as e:
        print(f"[图像编辑] 提交任务失败: {e}")
        raise RuntimeError(f"提交失败: {str(e)}")
    
    # 轮询结果
    while True:
        try:
            result = requests.get( 
                f"{api_base}v1/tasks/{task_id}", 
                headers={**headers, "X-ModelScope-Task-Type": "image_generation"}, 
            )
            result.raise_for_status()
            data = result.json()
        except Exception as e:
            print(f"[图像编辑] 轮询出错: {e}")
            raise RuntimeError(f"轮询失败: {str(e)}")
            
        status = data["task_status"]
        print(f"[图像编辑] 当前任务状态: {status}")
        
        if status == "SUCCEED":
            raw_out = data.get("output_images")
            if isinstance(raw_out, list) and raw_out:
                output_url = raw_out[0]
            elif isinstance(raw_out, str):
                output_url = raw_out
            else:
                raise RuntimeError(f"无法解析 output_images: {raw_out!r}")
            print(f"[图像编辑] 编辑成功，结果图 URL: {output_url}")
            try:
                img_data = requests.get(output_url).content
                image = _pil_to_rgb(Image.open(BytesIO(img_data)))
                new_name = f"{uuid.uuid4().hex}.jpg"
                save_image_path = UPLOAD_IMAGE_DIR / new_name
                image.save(save_image_path)
                print(f"[图像编辑] 结果图已保存至: {save_image_path}")
                return image
            except Exception as e:
                raise RuntimeError(f"下载结果图失败: {str(e)}")
        elif status == "FAILED":
            error_msg = data.get("error", "未知错误")
            print(f"[图像编辑] 任务失败: {error_msg}")
            raise RuntimeError(f"ModelScope 编辑失败: {error_msg}")
        time.sleep(5)

def handle_image_edit(model_name: str, user_token: str, prompt: str, image1: str, image2: str, image3: str):
    """ Gradio 回调函数：处理图像编辑请求 """
    uploaded_files = [image1, image2, image3]
    uploaded_files = [t for t in uploaded_files if t]
    if not uploaded_files:
        raise ValueError("请至少上传一张图片！")
    if not prompt or not prompt.strip():
        raise ValueError("请输入有效的编辑提示词！")
    if not user_token or not user_token.strip():
        raise ValueError("请先输入 ModelScope Token！可在如下地址获取：https://www.modelscope.cn/my/myaccesstoken")
    
    print(f"[图像编辑] 开始处理请求，共 {len(uploaded_files)} 张图片")
    
    # 保存上传的文件到本地目录（确保长期可访问）
    saved_paths = []
    for file_path in uploaded_files:
        ext = os.path.splitext(file_path).lower() or ".jpg"
        new_name = f"{uuid.uuid4().hex}{ext}"
        dest_path = UPLOAD_IMAGE_DIR / new_name
        with open(file_path, "rb") as src, open(dest_path, "wb") as dst:
            dst.write(src.read())
        saved_paths.append(str(dest_path))
        print(f"[图像编辑] 已保存图片: {dest_path}")
    
    # 调用 API 编辑
    edited_image = edit_image_via_modelscope(model_name, prompt, saved_paths, user_token)
    return edited_image

# ========== 逻辑处理函数 ==========
import requests
import time
import json
from PIL import Image
from io import BytesIO

def call_modelscope_api(model_id: str, token: str, prompt: str, size_str: str):
    """
    调用 ModelScope 图像生成 API 的函数
    """
    if not token or not token.strip():
        return None, "错误：请先输入有效的 ModelScope Token！可在如下地址获取：https://www.modelscope.cn/my/myaccesstoken"
    if not prompt or not prompt.strip():
        return None, "错误：提示词不能为空"
        
    # 1. 解析尺寸字符串 (例如 "1:1")
    try:
        aspect_ratios = {
            "1:1": (1328, 1328),
            "16:9": (1664, 928),
            "9:16": (928, 1664),
            "4:3": (1472, 1104),
            "3:4": (1104, 1472),
            "3:2": (1584, 1056),
            "2:3": (1056, 1584),
        }

        width, height = aspect_ratios.get(size_str, (1328, 1328))
    except Exception as e:
        return None, f"尺寸解析错误: {str(e)}"

    base_url = 'https://api-inference.modelscope.cn/'
    headers = { 
        "Authorization": f"Bearer {token.strip()}", 
        "Content-Type": "application/json", 
    }
    
    # 2. 提交异步任务
    try:
        payload = { 
            "model": model_id, 
            "prompt": prompt,
            # 如果API支持直接传入宽高，请取消下面两行注释
            "width": width,
            "height": height
        }
        
        response = requests.post( 
            f"{base_url}v1/images/generations", 
            headers={**headers, "X-ModelScope-Async-Mode": "true"}, 
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8') 
        )
        response.raise_for_status()
        task_id = response.json()["task_id"]
        yield None, f"✅ 任务提交成功，Task ID: {task_id} (轮询中...)"
        
    except Exception as e:
        error_msg = response.json().get("message", str(e)) if 'response' in locals() else str(e)
        return None, f"❌ 提交失败: {error_msg}"

    start_time = time.time()
    # 3. 轮询结果
    while True:
        try:
            result = requests.get( 
                f"{base_url}v1/tasks/{task_id}", 
                headers={**headers, "X-ModelScope-Task-Type": "image_generation"}, 
            )
            result.raise_for_status()
            data = result.json()
        except Exception as e:
            yield None, f"❌ 轮询请求出错: {str(e)}"
            break
            
        status = data["task_status"]
        yield None, f"🔄 当前状态: {status}"
        
        if status == "SUCCEED":
            try:
                output_url = data["output_images"][0] # 假设返回的是列表
                img_data = requests.get(output_url).content
                image = _pil_to_rgb(Image.open(BytesIO(img_data)))
                yield image, f"✅ 生成成功！尺寸: {image.size}"
            except Exception as e:
                yield None, f"❌ 下载或打开图片失败: {str(e)}"
            break
        elif status == "FAILED":
            error_msg = data.get("error", "未知错误")
            yield None, f"❌ 任务失败: {error_msg}"
            break
        else:
            time.sleep(5) # 等待5秒后再次查询

        current_time = time.time()
        if current_time -start_time > 10*60:
            error_msg = "超时"
            yield None, f"❌ 任务失败: {error_msg}"
            break


# ========== Gradio UI ==========
with gr.Blocks(title="Z-Image-Turbo Image Generator") as demo:
    gr.Markdown("Z-Image-Turbo官方体验[地址](https://www.modelscope.cn/studios/Tongyi-MAI/Z-Image-Gallery)；[图像分层](https://modelscope.cn/studios/Qwen/Qwen-Image-Layered/summary)")
    
    with gr.Tab("🖼️ Z-Image 图像生成器"):
        with gr.Row():
            with gr.Column():
                prompt_input = gr.Textbox( 
                    label="提示词 (Prompt)", 
                    placeholder="例如: 一只赛博格蝗虫，拥有透明皮肤、白色骨架结构，内部的线路和电路板清晰可见，采用微距摄影技术在森林中拍摄，带有照片特效。", 
                    lines=3 
                )
                ratio_dropdown = gr.Dropdown( 
                    choices=list(ASPECT_RATIOS.keys()), 
                    value="16:9", 
                    label="图像比例 (Aspect Ratio)" 
                )
                generate_btn = gr.Button("生成图像", variant='primary')
            with gr.Column():
                output_image = gr.Image(label="生成结果", format='png', type="pil")
                
        generate_btn.click( 
            fn=generate_image, 
            inputs=[prompt_input, ratio_dropdown], 
            outputs=output_image 
        )

    # ========== 新增：API 接口调用 Tab ==========
    with gr.Tab("☁️ API 生成图片"):
        gr.Markdown("""
        ## 通过 ModelScope API 云端生成
        输入 **ModelScope Token**，选择云端模型，通过远程 API 生成图像。
        获取 Token [地址](https://www.modelscope.cn/my/myaccesstoken)
        """)
        
        with gr.Row():
            with gr.Column(scale=2):
                
                # 提示词输入
                api_prompt_input = gr.Textbox(
                    label="提示词 (Prompt)",
                    placeholder="例如: A golden cat",
                    lines=3
                )
                
                # 尺寸下拉选择
                # 注意：这里的选项是根据你提供的API文档中的 aspect_ratios 字典整理的
                size_choices = [
                    "1:1", 
                    "16:9", 
                    "9:16", 
                    "4:3", 
                    "3:4",
                    "3:2",
                    "2:3"
                ]
                api_size_dropdown = gr.Dropdown(
                    choices=size_choices,
                    value="16:9",
                    label="图像尺寸 (Aspect Ratio & Resolution)"
                )
                
                # 生成按钮
                api_generate_btn = gr.Button("🚀 请求 API 生成", variant="primary")
                
            with gr.Column(scale=3):
                
                # 模型选择（包含了文档示例中的模型ID）
                api_model_dropdown = gr.Dropdown(
                    choices=[
                        "Qwen/Qwen-Image-2512",
                        "Qwen/Qwen-Image",
                        "MusePublic/489_ckpt_FLUX_1",
                        "laonansheng/xuner-zhongzhou-Qwen-Image-2512-v1.0",
                        "Tongyi-MAI/Z-Image", 
                        "Tongyi-MAI/Z-Image-Turbo",
                        "laonansheng/meixiong-niannian-Z-Image-Turbo-Tongyi-MAI-v1.0", 
                        "laonansheng/ruanqing-Z-Image-Turbo-Tongyi-MAI-v1.0",
                        "Wuli-Art/Qwen-Image-2512-Turbo-LoRA-2-Steps",
                        "KookYan/Kook_Qwen_2512_jzzs",
                        "KookYan/Kook_Qwen_2512_Zshx",
                        "laonansheng/Asian-beauty-Z-Image-Turbo-Tongyi-MAI-v1.0",
                        "Muki182/r18_pose_real_sdxl",
                        "qiyuanai/Qwen_Image_Strapless_Beauty_Model_Traffic_Code_INS_Douyin_Xiaohongshu_Kuaishou_Portrait_Photography_E_commerce",
                        "laonansheng/naixi-girl-Z-Image-Turbo-Tongyi-MAI-v1.0",
                    ],
                    value="Qwen/Qwen-Image-2512",
                    label="云端模型 ID (Model ID)"
                )
                
                # Token 输入
                api_token_input = gr.Textbox(
                    label="ModelScope Token",
                    placeholder="请输入你的 API Token (以 ms- 开头)",
                    type="password",
                    value=""
                )
                # 结果展示
                api_status_text = gr.Textbox(label="任务状态", interactive=False)
                api_output_image = gr.Image(label="API 生成结果", type="pil", show_download_button=True, height=500)
                
        # ========== 绑定事件 ==========
        # 点击按钮触发 API 调用
        api_generate_btn.click(
            fn=call_modelscope_api,
            inputs=[api_model_dropdown, api_token_input, api_prompt_input, api_size_dropdown],
            outputs=[api_output_image, api_status_text]
        )

    with gr.Tab("🤖 提示词优化"):
        gr.Markdown("获取访问令牌(ModelScope Token)[地址](https://www.modelscope.cn/my/myaccesstoken)")
        with gr.Row():
            task_dropdown = gr.Dropdown(
                choices=[
                    ("优化文生图提示词", "optimize_prompt"),
                    ("聊天", "chat")
                ],
                value="optimize_prompt",
                label="选择任务类型",
                interactive=True
            )

            model_name = gr.Dropdown(
                choices=[
                    "Qwen/Qwen3-8B",
                    'Qwen/Qwen3-14B',
                    "Qwen/Qwen3-32B",
                    'Qwen/Qwen3-235B-A22B-Instruct-2507',
                    "deepseek-ai/DeepSeek-V3.2",
                    'deepseek-ai/DeepSeek-R1-Distill-Qwen-32B',
                    'deepseek-ai/DeepSeek-R1-0528',
                    "ZhipuAI/GLM-4.7",
                    'XiaomiMiMo/MiMo-V2-Flash',
                ],
                value="Qwen/Qwen3-8B",
                label="选择模型",
                allow_custom_value=True,
                filterable=True
            )

            token_input = gr.Textbox(
                label="访问令牌(ModelScope Token)",
                placeholder="请输入你的 ModelScope API Token,如：ms-123sdwea-8w2d-98wd-9865-76w3e222123",
                type="password",
                value="",  # 默认为空，用户必须填写
            )

            max_turns_slider = gr.Slider(
                minimum=0,
                maximum=50,
                value=10,
                step=1,
                label="最大保留对话轮数",
                interactive=True
            )

        chatbot = gr.Chatbot(height=500)

        msg = gr.Textbox(
            label="输入内容",
            placeholder="开始输入...",
            value="一只小猫"
        )

        # 提交逻辑：传递 token 和 max_turns
        msg.submit(
            fn=user,
            inputs=[msg, chatbot, task_dropdown, max_turns_slider],
            outputs=[msg, chatbot, task_dropdown],
            queue=False
        ).then(
            fn=chat,
            inputs=[token_input, model_name, chatbot, task_dropdown, max_turns_slider],
            outputs=chatbot
        )

    with gr.Tab("✏️ 图像编辑"):
        gr.Markdown("""
        ## 图像编辑(Qwen-Image-Edit-2511)
        上传一张或多张图片（最多三张，大小不超过3M），输入编辑指令，并填写你的 **ModelScope Token**。
        获取 Token [地址](https://www.modelscope.cn/my/myaccesstoken)
        """)
        with gr.Row():
            with gr.Column():
                image1 = gr.Image(type="filepath", label="图1", height=180)
                image2 = gr.Image(type="filepath", label="图2(可选)", height=180, visible=False)
                image3 = gr.Image(type="filepath", label="图3(可选)", height=180, visible=False)
            with gr.Column():
                model_name = gr.Dropdown(
                    choices=[
                        'Qwen/Qwen-Image-Edit-2511',
                        'Qwen/Qwen-Image-Edit-2509',
                    ],
                    value='Qwen/Qwen-Image-Edit-2511',
                    label="选择模型",
                    allow_custom_value=True,
                    filterable=True
                )
                edit_token_input = gr.Textbox(
                    label="ModelScope Token",
                    placeholder="请输入你的 ModelScope API Token（以 ms- 开头）",
                    type="password",
                    value=""
                )

                edit_prompt_input = gr.Textbox(
                    label="编辑指令",
                    placeholder="""例1：给图中的猫戴上墨镜，背景换成海滩
例2：柔光，使用柔和的光线对图片进行重新照明
例3：将镜头平移至桌面特写
例4：将镜头向左旋30度
例5：把图1中的桌椅面板替换成图2的浅色木材质""",
                    lines=5
                )
                edit_btn = gr.Button("编辑图像", variant="primary")
        with gr.Column():
            edit_output_image = gr.Image(label="编辑结果", format='jpg', type="filepath", show_download_button=True)

        # 动态显示 image2：当 image1 有内容时
        image1.change(
            fn=lambda x: gr.update(visible=True) if x else gr.update(),
            inputs=image1,
            outputs=image2
        )

        # 动态显示 image3：当 image2 有内容时
        image2.change(
            fn=lambda x: gr.update(visible=True) if x else gr.update(),
            inputs=image2,
            outputs=image3
        )

        edit_btn.click(
            fn=handle_image_edit,
            inputs=[model_name, edit_token_input, edit_prompt_input, image1, image2, image3],
            outputs=edit_output_image
        )

# ========== FastAPI + Gradio Mount ==========
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse

# 挂载静态文件服务（本地开发时仍可访问，但实际调用使用公网 URL）
app.mount("/images", StaticFiles(directory=str(UPLOAD_IMAGE_DIR)), name="uploaded_images")

# 定义Pydantic模型用于请求体解析
class ImageRequest(BaseModel):
    prompt: str
    aspect_ratio: str


@app.post("/api")
async def api_generate_image(request: ImageRequest):
    # 参数校验
    if request.aspect_ratio not in ASPECT_RATIOS:
        raise HTTPException(status_code=400, detail=f"Invalid aspect_ratio. Choose from: {list(ASPECT_RATIOS.keys())}")

    try:
        image = generate_image(request.prompt, request.aspect_ratio)
        # 转为字节流返回
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return StreamingResponse(buffer, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 挂载 Gradio 应用到 /（避免与 /api 冲突）
app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    preload_models()
    uvicorn.run(app, host='0.0.0.0', port=7860)


'''
curl：
curl -X POST "http://localhost:7860/api" \
-H "Content-Type: application/json" \
-d '{"prompt": "a red apple on a wooden table", "aspect_ratio": "1:1"}' \
--output output.png

或者使用 Python 的 requests 库：

import requests

response = requests.post("http://localhost:7860/api",
                         json={"prompt": "a red apple on a wooden table", "aspect_ratio": "1:1"})
with open("result.png", "wb") as f:
    f.write(response.content)
    
'''

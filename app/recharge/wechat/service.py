import hashlib
import uuid
import xml.etree.ElementTree as ET
from typing import Dict, Optional
import httpx
import logging
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class WechatPayService:
    """微信支付服务"""
    
    def __init__(self):
        self.app_id = settings.wechat_app_id
        self.mch_id = settings.wechat_mch_id
        self.api_key = settings.wechat_api_key
        self.notify_url = f"{settings.app_name}/api/recharge/wechat/callback"
        self.unified_order_url = "https://api.mch.weixin.qq.com/pay/unifiedorder"
        
        logger.info(f"WechatPayService 初始化完成")
    
    def _generate_sign(self, params: Dict[str, str]) -> str:
        """
        生成微信支付签名
        
        Args:
            params: 参数字典
            
        Returns:
            签名字符串
        """
        # 1. 参数排序
        sorted_params = sorted(params.items(), key=lambda x: x[0])
        
        # 2. 拼接字符串
        sign_str = "&".join([f"{k}={v}" for k, v in sorted_params if v])
        sign_str += f"&key={self.api_key}"
        
        # 3. MD5加密并转大写
        sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
        
        logger.debug(f"签名字符串: {sign_str}")
        logger.debug(f"生成签名: {sign}")
        
        return sign
    
    def _dict_to_xml(self, data: Dict[str, str]) -> str:
        """将字典转换为XML"""
        xml_str = "<xml>"
        for k, v in data.items():
            xml_str += f"<{k}><![CDATA[{v}]]></{k}>"
        xml_str += "</xml>"
        return xml_str
    
    def _xml_to_dict(self, xml_str: str) -> Dict[str, str]:
        """将XML转换为字典"""
        root = ET.fromstring(xml_str)
        return {child.tag: child.text for child in root}
    
    def _verify_sign(self, data: Dict[str, str]) -> bool:
        """
        验证微信返回的签名
        
        Args:
            data: 微信返回的数据
            
        Returns:
            签名是否有效
        """
        sign = data.pop('sign', '')
        calculated_sign = self._generate_sign(data)
        return sign == calculated_sign
    
    async def create_native_order(
        self,
        out_trade_no: str,
        total_fee: int,
        body: str,
        attach: Optional[str] = None
    ) -> Dict[str, str]:
        """
        创建Native支付订单
        
        Args:
            out_trade_no: 商户订单号
            total_fee: 总金额（分）
            body: 商品描述
            attach: 附加数据（可选）
            
        Returns:
            包含code_url的字典
        """
        logger.info(f"创建微信Native支付订单: out_trade_no={out_trade_no}, total_fee={total_fee}")
        
        # 构建请求参数
        params = {
            'appid': self.app_id,
            'mch_id': self.mch_id,
            'nonce_str': uuid.uuid4().hex,
            'body': body,
            'out_trade_no': out_trade_no,
            'total_fee': str(total_fee),
            'spbill_create_ip': '127.0.0.1',  # 终端IP
            'notify_url': self.notify_url,
            'trade_type': 'NATIVE',
        }
        
        if attach:
            params['attach'] = attach
        
        # 生成签名
        params['sign'] = self._generate_sign(params)
        
        # 转换为XML
        xml_data = self._dict_to_xml(params)
        
        logger.debug(f"请求参数: {xml_data}")
        
        try:
            # 发送请求
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.unified_order_url,
                    content=xml_data.encode('utf-8'),
                    headers={'Content-Type': 'application/xml'}
                )
                
                logger.info(f"微信API响应状态码: {response.status_code}")
                
                # 解析响应
                result = self._xml_to_dict(response.text)
                
                logger.debug(f"微信API响应: {result}")
                
                # 检查返回状态
                if result.get('return_code') != 'SUCCESS':
                    error_msg = result.get('return_msg', '未知错误')
                    logger.error(f"微信支付下单失败: {error_msg}")
                    raise Exception(f"微信支付下单失败: {error_msg}")
                
                if result.get('result_code') != 'SUCCESS':
                    error_msg = result.get('err_code_des', '未知错误')
                    logger.error(f"微信支付业务失败: {error_msg}")
                    raise Exception(f"微信支付业务失败: {error_msg}")
                
                # 验证签名
                if not self._verify_sign(result.copy()):
                    logger.error("微信返回签名验证失败")
                    raise Exception("签名验证失败")
                
                logger.info(f"✅ 微信Native支付订单创建成功: code_url={result.get('code_url')}")
                
                return {
                    'code_url': result.get('code_url'),
                    'prepay_id': result.get('prepay_id')
                }
                
        except Exception as e:
            logger.error(f"❌ 创建微信支付订单失败: {e}", exc_info=True)
            raise
    
    async def query_order(self, out_trade_no: str) -> Dict[str, str]:
        """
        查询订单状态
        
        Args:
            out_trade_no: 商户订单号
            
        Returns:
            订单信息
        """
        logger.info(f"查询微信订单状态: out_trade_no={out_trade_no}")
        
        params = {
            'appid': self.app_id,
            'mch_id': self.mch_id,
            'out_trade_no': out_trade_no,
            'nonce_str': uuid.uuid4().hex,
        }
        
        params['sign'] = self._generate_sign(params)
        xml_data = self._dict_to_xml(params)
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    'https://api.mch.weixin.qq.com/pay/orderquery',
                    content=xml_data.encode('utf-8'),
                    headers={'Content-Type': 'application/xml'}
                )
                
                result = self._xml_to_dict(response.text)
                
                if result.get('return_code') != 'SUCCESS':
                    raise Exception(result.get('return_msg', '查询失败'))
                
                if result.get('result_code') != 'SUCCESS':
                    raise Exception(result.get('err_code_des', '查询失败'))
                
                logger.info(f"订单状态: {result.get('trade_state')}")
                return result
                
        except Exception as e:
            logger.error(f"查询订单失败: {e}", exc_info=True)
            raise
    
    def parse_notify(self, xml_data: str) -> Dict[str, str]:
        """
        解析微信支付回调通知
        
        Args:
            xml_data: 微信发送的XML数据
            
        Returns:
            解析后的数据字典
        """
        logger.info("解析微信支付回调通知")
        
        try:
            data = self._xml_to_dict(xml_data)
            
            # 验证签名
            if not self._verify_sign(data.copy()):
                logger.error("回调签名验证失败")
                raise Exception("签名验证失败")
            
            # 检查返回状态
            if data.get('return_code') != 'SUCCESS':
                raise Exception(data.get('return_msg', '未知错误'))
            
            if data.get('result_code') != 'SUCCESS':
                raise Exception(data.get('err_code_des', '未知错误'))
            
            logger.info(f"✅ 回调解析成功: out_trade_no={data.get('out_trade_no')}, transaction_id={data.get('transaction_id')}")
            
            return data
            
        except Exception as e:
            logger.error(f"解析回调失败: {e}", exc_info=True)
            raise
    
    def generate_notify_response(self, return_code: str = 'SUCCESS', return_msg: str = 'OK') -> str:
        """
        生成回调响应XML
        
        Args:
            return_code: 返回码
            return_msg: 返回信息
            
        Returns:
            XML响应字符串
        """
        return self._dict_to_xml({
            'return_code': return_code,
            'return_msg': return_msg
        })


# 创建全局实例
wechat_pay_service = WechatPayService()
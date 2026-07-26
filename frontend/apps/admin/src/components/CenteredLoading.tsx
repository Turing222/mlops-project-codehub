import React from 'react';
import { Spin } from 'antd';

/** 路由级懒加载与守卫共用的居中加载态。 */
const CenteredLoading: React.FC = () => (
    <div style={{ display: 'flex', justifyContent: 'center', marginTop: 100 }}>
        <Spin size="large" />
    </div>
);

export default CenteredLoading;

/*******************************************
舵机处理函数，处理串口解析出来的数值
然后让相应的舵机执行相应的动作值
 ******************************************/
void handle_duoji() {
    static unsigned long systick_ms_bak = 0;
    if(!handle_ms_between(&systick_ms_bak, DUOJI_MS_BETWEEN))return;  
    //Serial.end();    //关闭串口（避免串口中断影响舵机处理过程）
    for(byte i = 0; i < DJ_NUM; i++) {
        if(abs( duoji_doing[i].aim - duoji_doing[i].cur) <= abs (duoji_doing[i].inc) ) {
             myservo[i].writeMicroseconds(duoji_doing[i].aim);      
             duoji_doing[i].cur = duoji_doing[i].aim;
             myservo[i].detach();
             duoji_doing_flag[i] = 1;
        } else {
             duoji_doing[i].cur +=  duoji_doing[i].inc;
             myservo[i].writeMicroseconds((int)duoji_doing[i].cur); 
        }    
    }
    //Serial.begin(115200); //开启串口
    
}

void handle_duoji_r() {
  static long long systick_bak=0;
  if(millis() - systick_bak > 500) {
    systick_bak = millis();
    for(byte i=0;i<DJ_NUM;i++) {
      if(duoji_doing_flag[i]) {
          myservo[i].detach();
          duoji_doing_flag[i] = 0;
      }
    }
  }
}

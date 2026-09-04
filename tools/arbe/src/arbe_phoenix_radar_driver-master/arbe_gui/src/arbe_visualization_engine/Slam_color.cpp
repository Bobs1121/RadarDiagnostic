#include "Utils.h"
#include <arbe_msgs/arbeSlamMsg.h>
#include <arbe_msgs/arbeClassificationEnum.h>
#include <geometry_msgs/TwistWithCovarianceStamped.h>
#include "Slam_color.hpp"
Slam_Color* Slam_Color::m_pInstance = NULL;
Slam_Color::Slam_Color(uint64_t seed)
{
    std::srand(seed);
    uint8_t I=0;
    std::vector<uint8_t> ind;
	for(uint8_t i = 0; i < 64; i++)
		ind.push_back(i);
	std::random_shuffle(ind.begin(),ind.end());
    for(uint8_t i = 0; i < 4; i++){
        float r = i * 0.2 + 0.2;
        for(uint8_t j = 0; j < 4; j++){
            float g = j * 0.2 + 0.2;
            for(uint8_t k = 0; k < 4; k++,I++){
                float b = k * 0.2 + 0.2;
				color_a[ind[I]][0] = r;
				color_a[ind[I]][1] = g;
				color_a[ind[I]][2] = b;
			}
		}
	}
}
Slam_Color* Slam_Color::Instance()
{
    if (!m_pInstance)
        m_pInstance = new Slam_Color;
    return m_pInstance;
}
void Slam_Color::get_color(uint16_t id, float &r, float &g, float &b)
{
	uint8_t i = (uint8_t)(id % 64);
	r = color_a[i][0];
	g = color_a[i][1];
	b = color_a[i][2];
}
void Slam_Color::get_color_ui8(uint16_t id, uint8_t &r, uint8_t &g, uint8_t &b)
{
    float red,green,blue;
    get_color(id,red,green,blue);
    r = (uint8_t)(255 * red);
    g = (uint8_t)(255 * green);
    b = (uint8_t)(255 * blue);
}
void Slam_Color::get_class_color(uint8_t cl, float &red, float &green, float &blue, std::string &fc_txt)
{
	switch(cl)
	{
	case arbe_msgs::arbeClassificationEnum::CLS_PEDESTRIAN:
		fc_txt = ", Pedestrian";
		red = 1;
		green = 0;
		blue = 0;
		break;
	case arbe_msgs::arbeClassificationEnum::CLS_BICYCLE:
		fc_txt = ", Bicycle";
		red = 0;
		green = 1;
		blue = 1;
		break;
	case arbe_msgs::arbeClassificationEnum::CLS_MOTORCYCLE:
		fc_txt = ", Motorcycle";
		red = 0;
		green = 0.635;
		blue = 0.929;
		break;
    case arbe_msgs::arbeClassificationEnum::CLS_VEHICLE:
        fc_txt = ", Vehicle";
		red = 0.54;
		green = 0.17;
		blue = 0.89;
		break;
    case arbe_msgs::arbeClassificationEnum::CLS_2_WHEELER:
        fc_txt = ", 2 Wheeler";
        red = 0;
        green = 0;
        blue = 1;
        break;
    case arbe_msgs::arbeClassificationEnum::CLS_VRU:
        fc_txt = ", VRU";
        red = 1;
        green = 0;
        blue = 0.2;
        break;
    case arbe_msgs::arbeClassificationEnum::CLS_M_VEHICLE:
        fc_txt = ", M.Vehicle";
        red = 0;
        green = 0.2;
        blue = 0.7;
        break;
	default:
		fc_txt = "";
		red = 1;
		green = 0.8;
		blue = 0;
		break;
	}
}
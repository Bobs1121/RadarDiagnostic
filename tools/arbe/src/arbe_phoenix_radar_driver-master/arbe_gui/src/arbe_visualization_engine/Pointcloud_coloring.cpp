#define BOOST_MPL_CFG_NO_PREPROCESSED_HEADERS
#define BOOST_MPL_LIMIT_VECTOR_SIZE 30
#include "Utils.h"
#include <arbe_msgs/arbeSlamMsg.h>
#include <geometry_msgs/TwistWithCovarianceStamped.h>
#include "Slam_color.hpp"
#include "Pointcloud_coloring.hpp"
Color_Coding_Min_Max* Color_Coding_Min_Max::m_pInstance = NULL;
Color_Coding_Min_Max::Color_Coding_Min_Max()
{}
Color_Coding_Min_Max* Color_Coding_Min_Max::Instance()
{
    if (!m_pInstance)
        m_pInstance = new Color_Coding_Min_Max;
    return m_pInstance;
                                        }
void Color_Coding_Min_Max::set_min(std::string ColoringType, float min)
{
    if ( strcmp(ColoringType.c_str(), "Doppler") == 0 )
    {
        dopp_cc_min = min;
                                }
    else if ( strcmp(ColoringType.c_str(), "Dopp. Gradient") == 0 )
    {
        dopp_grad_cc_min = min * 4;
    }
    else if ( strcmp(ColoringType.c_str(), "Elevation") == 0 )
    {
       el_cc_min = min;
    }
    else 
    {
        amp_cc_min = (min) ;
    }
}
void Color_Coding_Min_Max::set_max(std::string ColoringType, float max)
{
    if ( strcmp(ColoringType.c_str(), "Doppler") == 0 )
    {
        dopp_cc_max = max;
                        }
    else if ( strcmp(ColoringType.c_str(), "Dopp. Gradient") == 0 )
    {
        dopp_grad_cc_max = max * 4;
                }
    else if ( strcmp(ColoringType.c_str(), "Elevation") == 0 )
    {
        el_cc_max = max;
    }
    else 
    {
        amp_cc_max = (max) ;
    }
}
void Color_Coding_Min_Max::get_values(std::string ColoringType, float &min, float &max)
{
    if ( strcmp(ColoringType.c_str(), "Doppler") == 0 )
    {
        min = dopp_cc_min;
        max = dopp_cc_max;
    }
    else if ( strcmp(ColoringType.c_str(), "Dopp. Gradient") == 0 )
    {
        min = dopp_grad_cc_min;
        max = dopp_grad_cc_max;
    }
    else if ( strcmp(ColoringType.c_str(), "Elevation") == 0 )
    {
        min = el_cc_min;
        max = el_cc_max;
    }
    else 
    {
        min = amp_cc_min;
        max = amp_cc_max;
    }
}
void Color_Coding_Min_Max::get_converted_values(std::string ColoringType, float &min, float &max)
{
    if ( strcmp(ColoringType.c_str(), "Doppler") == 0 )
    {
        min = dopp_cc_min;
        max = dopp_cc_max;
    }
    else if ( strcmp(ColoringType.c_str(), "Dopp. Gradient") == 0 )
    {
        min = dopp_grad_cc_min/4;
        max = dopp_grad_cc_max/4;
    }
    else if ( strcmp(ColoringType.c_str(), "Elevation") == 0 )
    {
        min = el_cc_min;
        max = el_cc_max;
    }
    else 
    {
        min = amp_cc_min;
        max = amp_cc_max;
    }
}
std::string Color_Coding_Min_Max::get_units(std::string ColoringType)
{
    if ( strcmp(ColoringType.c_str(), "Doppler") == 0 )
        return "m/s";
    else if ( strcmp(ColoringType.c_str(), "Dopp. Gradient") == 0 )
        return "m/s";
    else if ( strcmp(ColoringType.c_str(), "Elevation") == 0 )
        return "m";
    else 
        return "dB";
}
const int n_colors_jet = 4;
static float color_jet[n_colors_jet][3] = { {0,0,255}, {0,255,0}, {255,255,0}, {255,0,0} };
float normalize(float x, float min, float span)
{
	return (x-min)/span;
}
void apply_color(float z, uint8_t &r, uint8_t &g, uint8_t &b)
{
	int idx1;        
	int idx2;        
	float fractBetween = 0;  
	if(z <= 0) {  idx1 = idx2 = 0; }    
	else if(z >= 1)  {  idx1 = idx2 = n_colors_jet-1; }    
	else
	{
		z = z * (n_colors_jet-1);        
		idx1  = uint16_t(z); 
		idx2  = (idx1+1);                        	
		fractBetween = z - float(idx1); 
	}
	r = (color_jet[idx2][0] - color_jet[idx1][0])*fractBetween + color_jet[idx1][0];
	g = (color_jet[idx2][1] - color_jet[idx1][1])*fractBetween + color_jet[idx1][1];
	b = (color_jet[idx2][2] - color_jet[idx1][2])*fractBetween + color_jet[idx1][2];
}
void pointcloud_color_new( pcl::PointCloud<CornerRadarPointXYZRGBGeneric> &buffer, size_t j, float cc_min, float cc_max, std::string ColoringType)
{
    if ( strcmp(ColoringType.c_str(), "Doppler") == 0 )
    {
        uint8_t min_r = 0, min_g = 0, min_b = 255;   
        uint8_t max_r = 255, max_g = 0, max_b = 0;   
        if (buffer.points[j].doppler > cc_max) {
			buffer.points[j].r = 255;
			buffer.points[j].g = 0;
			buffer.points[j].b = 0;
		}
		else if (buffer.points[j].doppler < cc_min) {
			buffer.points[j].r = 0;
			buffer.points[j].g = 0;
			buffer.points[j].b = 255;
		}
		else {
            float ratio = std::min(std::max((buffer.points[j].doppler - cc_min) / (cc_max - cc_min), 0.0f), 1.0f);
            ratio = pow(ratio, 0.5f);
			buffer.points[j].r = static_cast<uint8_t>(min_r + ratio * (max_r - min_r));
			buffer.points[j].g = static_cast<uint8_t>(min_g + ratio * (max_g - min_g));
			buffer.points[j].b = static_cast<uint8_t>(min_b + ratio * (max_b - min_b));
		}
    }
    if ( strcmp(ColoringType.c_str(), "Elevation") == 0 )
    {
        float z = buffer.points[j].z;
        if(z<=0.2)
        {
            buffer.points[j].r = 0;
			buffer.points[j].g = 0;
			buffer.points[j].b = 254;
        }
        else if(z>0.2 && z<0.35)
        {
            buffer.points[j].r = 0;
			buffer.points[j].g = 125;
			buffer.points[j].b = 254;
        }
        else if(z>=0.35 && z<=1.4)
        {
            buffer.points[j].r = 0;
			buffer.points[j].g = 255;
			buffer.points[j].b = 255;
        }
        else if(z>1.4 && z<1.6)
        {
            buffer.points[j].r = 0;
			buffer.points[j].g = 255;
			buffer.points[j].b = 131;
        }
        else if(z>=1.6 && z<=3.5)
        {
            buffer.points[j].r = 0;
			buffer.points[j].g = 255;
			buffer.points[j].b = 0;
        }
        else if(z>3.5 && z<4.5)
        {
            buffer.points[j].r = 124;
			buffer.points[j].g = 255;
			buffer.points[j].b = 1;
        }
        else if(z>=4.5 && z<=12)
        {
            buffer.points[j].r = 255;
			buffer.points[j].g = 255;
			buffer.points[j].b = 0;
        }
        else if(z>12)
        {
            buffer.points[j].r = 255;
			buffer.points[j].g = 130;
			buffer.points[j].b = 1; 
        }
    }
    else if(strcmp(ColoringType.c_str(), "GhostType") == 0)
    {
        uint8_t min_r = 0, min_g = 0, min_b = 255;   
        uint8_t max_r = 255, max_g = 0, max_b = 0;   
        if ((buffer.points[j].ghost_type == 0) || (buffer.points[j].ghost_type == 101)) {
			buffer.points[j].r = 0;
			buffer.points[j].g = 0;
			buffer.points[j].b = 255;
		}
		else {
			buffer.points[j].r = 255;
			buffer.points[j].g = 0;
			buffer.points[j].b = 0;
		}
    }
    else if((strcmp(ColoringType.c_str(), "Normal") == 0) || (strcmp(ColoringType.c_str(), "DotClean") == 0))
    {
        switch (buffer.points[j].move_flag)
        {
            case 0:
                buffer.points[j].r = 255;
                buffer.points[j].g = 255;
                buffer.points[j].b = 255;        
                break;
            case 1:
                if((cc_min ==1)||(cc_min ==3))
                {   
                    buffer.points[j].r = 163;
                    buffer.points[j].g = 50;
                    buffer.points[j].b = 204;  
                }
                else
                {   
                    buffer.points[j].r = 128;
                    buffer.points[j].g = 0;
                    buffer.points[j].b = 128;  
                }
                break;
            case 2:
                if((cc_min ==1)||(cc_min ==3))
                {   
                    buffer.points[j].r = 144;
                    buffer.points[j].g = 238;
                    buffer.points[j].b = 144;  
                }
                else
                {   
                    buffer.points[j].r = 0;
                    buffer.points[j].g = 128;
                    buffer.points[j].b = 0;  
                }        
                break;
            case 3:
                buffer.points[j].r = 255;
                buffer.points[j].g = 0;
                buffer.points[j].b = 0;  
                break;
            default:
                break;
        }
    }
    else if(strcmp(ColoringType.c_str(), "GhostCheck") == 0)
    {
        if(buffer.points[j].ghost_type == 0)
        {
            switch (buffer.points[j].move_flag)
            {
                case 0:
                    buffer.points[j].r = 255;
                    buffer.points[j].g = 255;
                    buffer.points[j].b = 255;        
                    break;
                case 1:
                    if((cc_min ==1)||(cc_min ==3))
                    {   
                        buffer.points[j].r = 163;
                        buffer.points[j].g = 50;
                        buffer.points[j].b = 204;  
                    }
                    else
                    {   
                        buffer.points[j].r = 128;
                        buffer.points[j].g = 0;
                        buffer.points[j].b = 128;  
                    }
                    break;
                case 2:
                    if((cc_min ==1)||(cc_min ==3))
                    {   
                        buffer.points[j].r = 144;
                        buffer.points[j].g = 238;
                        buffer.points[j].b = 144;  
                    }
                    else
                    {   
                        buffer.points[j].r = 0;
                        buffer.points[j].g = 128;
                        buffer.points[j].b = 0;  
                    }        
                    break;
                case 3:
                    buffer.points[j].r = 255;
                    buffer.points[j].g = 0;
                    buffer.points[j].b = 0;  
                    break;
                default:
                    break;
            }
        }
        else if (buffer.points[j].ghost_type == 101)
        {
            buffer.points[j].r = 0;
            buffer.points[j].g = 0;
            buffer.points[j].b = 255;   
        }
        else if (buffer.points[j].ghost_type == 102)
        {
            buffer.points[j].r = 255;
            buffer.points[j].g = 255;
            buffer.points[j].b = 0;   
        }
        else
        {
            buffer.points[j].r = 255;
            buffer.points[j].g = 0;
            buffer.points[j].b = 0;   
        }
    }
}
void pointcloud_color_new1( pcl::PointCloud<CornerRadarPointXYZRGBGeneric> &buffer, size_t j, curbDBSCANOutput algo_curbDBSCAN, rbExt_CStaticConfiguration algo_RadarPos, std::string ColoringType)
{
    if ( strcmp(ColoringType.c_str(), "Doppler") == 0 )
    {
        buffer.points[j].r = 255;
        buffer.points[j].g = 255;
        buffer.points[j].b = 255;
        if(algo_RadarPos.m_mountingPosition.radar_pos <= RadarPos_FrontRight)
        {
            if(algo_curbDBSCAN.mainLeftCurbNum > 0)
            {
                uint8_t mainLeftCurbID = algo_curbDBSCAN.curbVer[algo_curbDBSCAN.mainLeftCurbIDIndex].curbID;
                if (buffer.points[j].curb_id ==  mainLeftCurbID) 
                {
                    buffer.points[j].r = 255;
                    buffer.points[j].g = 0;
                    buffer.points[j].b = 0;
                }
            }
            if(algo_curbDBSCAN.mainRightCurbNum > 0)
            {
                uint8_t mainRightCurbID = algo_curbDBSCAN.curbVer[algo_curbDBSCAN.mainRightCurbIDIndex].curbID;
                if (buffer.points[j].curb_id ==  mainRightCurbID)
                {
                    buffer.points[j].r = 255;
                    buffer.points[j].g = 128;
                    buffer.points[j].b = 0;
                }               
            }
        }
        else
        {
            if(algo_curbDBSCAN.mainLeftCurbNum > 0)
            {
                uint8_t mainRightCurbID = algo_curbDBSCAN.curbVer[algo_curbDBSCAN.mainRightCurbIDIndex].curbID;
                if (buffer.points[j].curb_id ==  mainRightCurbID) 
                {
                    buffer.points[j].r = 255;
                    buffer.points[j].g = 0;
                    buffer.points[j].b = 0;
                }
            }
            if(algo_curbDBSCAN.mainRightCurbNum > 0)
            {
                uint8_t mainLeftCurbID = algo_curbDBSCAN.curbVer[algo_curbDBSCAN.mainLeftCurbIDIndex].curbID;
                if (buffer.points[j].curb_id ==  mainLeftCurbID)
                {
                    buffer.points[j].r = 255;
                    buffer.points[j].g = 128;
                    buffer.points[j].b = 0;
                }
            }
        }
        if(algo_curbDBSCAN.commonCredVerCurbNum > 0)
        {
            int tempCount = 0;
            for(int i = 0; i < 4; i++)
            {
                if (tempCount < algo_curbDBSCAN.commonCredVerCurbNum)
                {
                    if (i != algo_curbDBSCAN.mainLeftCurbIDIndex && i != algo_curbDBSCAN.mainRightCurbIDIndex)
                    {
                        uint8_t commonCurbID = algo_curbDBSCAN.curbVer[i].curbID;
                        if (buffer.points[j].curb_id ==  commonCurbID) 
                        {
                            buffer.points[j].r = 0;
                            buffer.points[j].g = 255;
                            buffer.points[j].b = 0;
                        }
                        tempCount++;
                    }
                }
                else
                {
                    break;
                }               
            }
        }
    }
}
void pointcloud_color( pcl::PointCloud<ArbePointXYZRGBGeneric> &buffer, size_t j, float cc_min, float cc_max, float cc_span, std::string ColoringType, float ego_velocity, float installation_ang, uint16_t track_id) 
{
	if (std::isnan(buffer.points[j].z)) buffer.points[j].z = 0;
	if(track_id > 0)
	{
		Slam_Color::Instance()->get_color_ui8(track_id, buffer.points[j].r, buffer.points[j].g, buffer.points[j].b);
	}
	else if ( strcmp(ColoringType.c_str(), "Doppler") == 0 )
	{
        float rel_speed = (buffer.points[j].doppler + ego_velocity* cos(-installation_ang - buffer.points[j].azimuth)); 
		if (rel_speed > cc_max) {
			buffer.points[j].r = 0;
			buffer.points[j].g = 0;
			buffer.points[j].b = 255;
		}
		else if (rel_speed < cc_min) {
			buffer.points[j].r = 255;
			buffer.points[j].g = 0;
			buffer.points[j].b = 0;
		}
		else {
			buffer.points[j].r = 0;
			buffer.points[j].g = 255;
			buffer.points[j].b = 0;
		}
	}
	else
	{
		float x, z;
		if ( strcmp(ColoringType.c_str(), "Dopp. Gradient") == 0 )
		{
            x = (buffer.points[j].doppler +  ego_velocity* cos(-installation_ang - buffer.points[j].azimuth));
		}
		else if ( (strcmp(ColoringType.c_str(), "Amplitude") == 0)  || (strcmp(ColoringType.c_str(), "Amplitude-Flat") == 0 )
			|| (strcmp(ColoringType.c_str(), "Range/Doppler") == 0 ))
		{
			x = buffer.points[j].snr;
		}
		else
		{
			x = buffer.points[j].z;
		}
		z = normalize(x, cc_min, cc_span);
		apply_color(z,buffer.points[j].r,buffer.points[j].g,buffer.points[j].b);
	}
	buffer.points[j].a = 0.2;
}
void pointcloud_one_color( pcl::PointCloud<CornerRadarPointXYZRGBGeneric> &buffer, size_t j, uint8_t r, uint8_t g, uint8_t b) 
{
	if (std::isnan(buffer.points[j].z)) buffer.points[j].z = 0;
	buffer.points[j].r = r;
	buffer.points[j].g = g;
	buffer.points[j].b = b;
	buffer.points[j].a = 0.2;
}